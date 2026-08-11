"""Isolated PostgreSQL smoke test for the Agent write-confirmation boundary.

Run against the dedicated, empty migrated test database:
    DATABASE_URL=postgresql+asyncpg://...@127.0.0.1:64236/codex_legacy_smoke_20260728 \
      PYTHONPATH=. python tests/agent_confirmation_smoke.py
"""

# The disposable-target guard intentionally runs before importing application
# modules, because those modules construct the database engine at import time.
# ruff: noqa: E402

import asyncio
import os
import uuid
from datetime import datetime
from decimal import Decimal
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

def _require_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        parsed = urlsplit(database_url)
        database_name = unquote(parsed.path.lstrip("/"))
        target = (
            parsed.scheme,
            parsed.hostname,
            parsed.port,
            database_name,
            parsed.query,
            parsed.fragment,
        )
    except ValueError as exc:
        raise RuntimeError("refusing_invalid_database_url") from exc
    if target != (
        "postgresql+asyncpg",
        "127.0.0.1",
        64236,
        "codex_legacy_smoke_20260728",
        "",
        "",
    ):
        raise RuntimeError(
            "refusing_non_disposable_database:"
            "expected_127.0.0.1_64236_codex_legacy_smoke_20260728"
        )


_require_disposable_database()

import app.agent.agent as agent_module
from app.agent.agent import cancel_pending_action, confirm_pending_action
from app.agent.state import collect_expected_versions, json_value, state_fingerprint
from app.agent.tools import TOOL_EFFECTS, dispatch_tool, prepare_pending_tool_call, public_tool_args
from app.core.db import AsyncSessionLocal
from app.core.family_scope import RequestContext, bind_request_context
from app.models import (
    Account,
    AgentOperationLog,
    AgentPendingAction,
    AgentSession,
    Family,
    FamilyMembership,
    Holding,
    Institution,
    Instrument,
    Owner,
    Transaction,
    User,
)
from app.models.enums import AssetClass, TransactionType
from app.schemas.agent import ChatMessage
from app.services import transaction_service, undo_service
from app.services.auth_service import ensure_initial_user


def _stage(
    confirmation_id: uuid.UUID,
    tool: str,
    args: dict,
) -> tuple[dict, dict]:
    stored_args, preview = prepare_pending_tool_call(tool, args, confirmation_id)
    call = {
        "id": str(uuid.uuid4()),
        "tool": tool,
        "effect": TOOL_EFFECTS[tool],
        "resource": tool.split("_", 1)[-1],
        "args": json_value(public_tool_args(stored_args)),
        "_dispatch_args": json_value(stored_args),
    }
    return call, preview


async def _pending(
    db,
    session_id: uuid.UUID,
    user_message: str,
    calls: list[dict],
    action_id: uuid.UUID,
) -> AgentPendingAction:
    expected_versions = await collect_expected_versions(db, calls)
    action = AgentPendingAction(
        id=action_id,
        session_id=session_id,
        user_message=user_message,
        turn_index=0,
        status="pending",
        state_hash=state_fingerprint(expected_versions),
        expected_versions_json=expected_versions,
        tool_calls_json=calls,
        result_trace_json=[],
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return action


async def _bind_default_family(db) -> None:
    await ensure_initial_user(db, "admin", "change-me")
    user = (
        await db.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    family = (
        await db.execute(select(Family).where(Family.slug == "default-family"))
    ).scalar_one()
    membership = (
        await db.execute(
            select(FamilyMembership).where(
                FamilyMembership.family_id == family.id,
                FamilyMembership.user_id == user.id,
                FamilyMembership.is_active.is_(True),
            )
        )
    ).scalar_one()
    bind_request_context(
        db,
        RequestContext(
            user_id=user.id,
            family_id=family.id,
            role=membership.role,
            token_jti=uuid.uuid4(),
        ),
    )


async def main() -> None:
    _require_disposable_database()
    async with AsyncSessionLocal() as db:
        await _bind_default_family(db)

        class FakeChatClient:
            def __init__(self) -> None:
                self.calls = 0

            async def chat(self, messages, tools=None):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "staging-gate-call",
                                "type": "function",
                                "function": {
                                    "name": "create_owner",
                                    "arguments": '{"name":"Gate Test Owner","owner_type":"individual"}',
                                },
                            }
                        ],
                    }
                return {"content": "Prepared the requested change.", "tool_calls": []}

        fake_client = FakeChatClient()
        original_get_active_client = agent_module.get_active_client

        async def fake_get_active_client(db, role):
            return fake_client

        agent_module.get_active_client = fake_get_active_client
        try:
            staged_turn = await agent_module.run_agent_turn(
                db,
                [ChatMessage(role="user", content="Create Gate Test Owner")],
            )
        finally:
            agent_module.get_active_client = original_get_active_client
        assert staged_turn.pending_action and staged_turn.pending_action.status == "pending"
        assert (
            await db.execute(select(Owner).where(Owner.name == "Gate Test Owner"))
        ).scalar_one_or_none() is None
        await cancel_pending_action(db, staged_turn.pending_action.id)

        session = AgentSession(title="Agent confirmation integration")
        db.add(session)
        await db.commit()
        session_id = session.id

        action_id = uuid.uuid4()
        owner_call, owner_preview = _stage(
            action_id,
            "create_owner",
            {"name": "王晓丽", "owner_type": "individual"},
        )
        institution_call, institution_preview = _stage(
            action_id,
            "create_institution",
            {"name": "Morgan Stanley", "institution_type": "broker"},
        )
        account_call, account_preview = _stage(
            action_id,
            "create_account",
            {
                "name": "Morgan Stanley Brokerage",
                "owner_id": owner_preview["reserved_id"],
                "institution_id": institution_preview["reserved_id"],
                "account_type": "brokerage",
                "base_currency": "USD",
            },
        )
        instrument_call, instrument_preview = _stage(
            action_id,
            "create_instrument",
            {
                "name": "SPDR S&P 500 ETF Trust",
                "symbol": "SPY",
                "asset_class": "etf",
                "currency": "USD",
                "market": "US",
                "price_source_type": "market",
            },
        )
        deposit_call, _ = _stage(
            action_id,
            "create_cash_transaction",
            {
                "account_id": account_preview["reserved_id"],
                "amount": 548000,
                "currency": "USD",
                "transaction_type": "deposit",
                "trade_date": "2026-07-21",
                "executed_at": "2026-07-21T10:59:00-04:00",
            },
        )
        buy_call, _ = _stage(
            action_id,
            "create_buy_transaction",
            {
                "account_id": account_preview["reserved_id"],
                "instrument_id": instrument_preview["reserved_id"],
                "quantity": 800,
                "price": 685,
                "currency": "USD",
                "fee": 0,
                "trade_date": "2026-07-21",
                "executed_at": "2026-07-21T11:00:00-04:00",
            },
        )
        calls = [
            owner_call,
            institution_call,
            account_call,
            instrument_call,
            deposit_call,
            buy_call,
        ]
        await _pending(db, session_id, "录入 SPY 买入", calls, action_id)

        # Staging a plan must not touch portfolio business tables.
        assert int((await db.execute(select(func.count()).select_from(Owner))).scalar_one()) == 0
        assert int((await db.execute(select(func.count()).select_from(Institution))).scalar_one()) == 0
        assert int((await db.execute(select(func.count()).select_from(Account))).scalar_one()) == 0
        assert int((await db.execute(select(func.count()).select_from(Transaction))).scalar_one()) == 0

        result = await confirm_pending_action(db, action_id)
        assert result.pending_action and result.pending_action.status == "confirmed"
        assert len(result.tool_call_trace) == 6
        owner_id = uuid.UUID(owner_preview["reserved_id"])
        institution_id = uuid.UUID(institution_preview["reserved_id"])
        account_id = uuid.UUID(account_preview["reserved_id"])
        instrument_id = uuid.UUID(instrument_preview["reserved_id"])
        assert await db.get(Owner, owner_id)
        assert await db.get(Institution, institution_id)
        assert await db.get(Account, account_id)
        assert await db.get(Instrument, instrument_id)
        tx = (
            await db.execute(
                select(Transaction).where(
                    Transaction.transaction_type == TransactionType.BUY
                )
            )
        ).scalar_one()
        assert tx.quantity == Decimal("800")
        assert tx.price == Decimal("685")
        assert tx.amount == Decimal("-548000.00")
        assert tx.fee == Decimal("0")
        assert tx.executed_at == datetime(2026, 7, 21, 15, 0, tzinfo=ZoneInfo("UTC"))
        asset_holding = (
            await db.execute(
                select(Holding).where(
                    Holding.account_id == account_id,
                    Holding.instrument_id == instrument_id,
                )
            )
        ).scalar_one()
        assert asset_holding.quantity == Decimal("800")

        # Repeated confirmation is idempotent.
        repeated = await confirm_pending_action(db, action_id)
        assert repeated.pending_action and repeated.pending_action.status == "confirmed"
        assert int((await db.execute(select(func.count()).select_from(Transaction))).scalar_one()) == 2

        # A single Agent confirmation batch cannot amend the same transaction
        # twice: that chain cannot be represented as one honest atomic undo.
        ambiguous_metadata_id = uuid.uuid4()
        first_metadata_call, _ = _stage(
            ambiguous_metadata_id,
            "update_transaction_metadata",
            {"transaction_id": str(tx.id), "note": "first amendment"},
        )
        second_metadata_call, _ = _stage(
            ambiguous_metadata_id,
            "update_transaction_metadata",
            {"transaction_id": str(tx.id), "note": "second amendment"},
        )
        await _pending(
            db,
            session_id,
            "重复修改同一交易元数据",
            [first_metadata_call, second_metadata_call],
            ambiguous_metadata_id,
        )
        event_count_before_ambiguous_plan = int(
            (await db.execute(select(func.count()).select_from(Transaction))).scalar_one()
        )
        ambiguous_result = await confirm_pending_action(
            db,
            ambiguous_metadata_id,
        )
        assert (
            ambiguous_result.pending_action
            and ambiguous_result.pending_action.status == "stale"
            and ambiguous_result.pending_action.error
            == "agent_plan_duplicate_transaction_metadata_update"
        )
        assert (
            int(
                (
                    await db.execute(
                        select(func.count()).select_from(Transaction)
                    )
                ).scalar_one()
            )
            == event_count_before_ambiguous_plan
        )

        # commit=False updates must eagerly fetch server-side updated_at values;
        # serializing a normal update must never perform implicit async IO.
        updated_owner = await dispatch_tool(
            db,
            "update_owner",
            {"owner_id": str(owner_id), "display_order": 7},
            commit=False,
        )
        assert updated_owner["display_order"] == 7
        assert updated_owner["updated_at"]
        await db.rollback()
        restored_owner = await db.get(Owner, owner_id)
        assert restored_owner and restored_owner.display_order == 0
        # Preserve the first operation log before adding the cash reconciliation.
        log = (
            await db.execute(
                select(AgentOperationLog).where(
                    AgentOperationLog.session_id == session_id,
                    AgentOperationLog.operation_type == "tool_call",
                )
            )
        ).scalar_one()

        # Setting an exact cash balance is an auditable delta transaction. It
        # must serialize without MissingGreenlet and survive ledger rebuilds.
        cash_action_id = uuid.uuid4()
        cash_call, _ = _stage(
            cash_action_id,
            "set_cash_balance",
            {
                "account_id": str(account_id),
                "currency": "USD",
                "balance": 1000,
                "trade_date": "2026-07-21",
                "note": "Opening cash balance reconciliation",
            },
        )
        await _pending(db, session_id, "现金余额校正", [cash_call], cash_action_id)
        cash_result = await confirm_pending_action(db, cash_action_id)
        assert cash_result.pending_action and cash_result.pending_action.status == "confirmed"
        assert cash_result.tool_call_trace[0]["error"] is None
        assert cash_result.tool_call_trace[0]["result"]["adjustment"] == "1000.000000"

        cash_instrument = (
            await db.execute(
                select(Instrument).where(
                    Instrument.asset_class == AssetClass.CASH,
                    Instrument.symbol == "USD",
                )
            )
        ).scalar_one()
        cash_holding = (
            await db.execute(
                select(Holding).where(
                    Holding.account_id == account_id,
                    Holding.instrument_id == cash_instrument.id,
                )
            )
        ).scalar_one()
        assert cash_holding.quantity == Decimal("1000")
        cash_adjustment = (
            await db.execute(
                select(Transaction).where(
                    Transaction.account_id == account_id,
                    Transaction.instrument_id == cash_instrument.id,
                    Transaction.transaction_type == TransactionType.RECONCILIATION,
                )
            )
        ).scalar_one()
        assert cash_adjustment.quantity == Decimal("1000")

        await transaction_service.recalculate_holdings_from_ledger(db)
        cash_holding = (
            await db.execute(
                select(Holding).where(
                    Holding.account_id == account_id,
                    Holding.instrument_id == cash_instrument.id,
                )
            )
        ).scalar_one()
        assert cash_holding.quantity == Decimal("1000")

        cash_log = (
            await db.execute(
                select(AgentOperationLog).where(
                    AgentOperationLog.session_id == session_id,
                    AgentOperationLog.operation_type == "tool_call",
                    AgentOperationLog.user_message == "现金余额校正",
                )
            )
        ).scalar_one()
        await undo_service.undo_agent_operation(db, cash_log.id)

        # Undo is append-only compensation. CRUD entities remain, while the
        # cash adjustment and original purchase are reversed in ledger order.
        await undo_service.undo_agent_operation(db, log.id)
        assert await db.get(Owner, owner_id)
        assert await db.get(Institution, institution_id)
        assert await db.get(Account, account_id)
        assert await db.get(Instrument, instrument_id)
        await db.refresh(asset_holding)
        await db.refresh(cash_holding)
        assert asset_holding.quantity == Decimal("0")
        assert cash_holding.quantity == Decimal("0")
        assert int((await db.execute(select(func.count()).select_from(Transaction))).scalar_one()) == 6

        # Cancellation performs no business write.
        cancel_id = uuid.uuid4()
        cancel_call, _ = _stage(
            cancel_id,
            "create_owner",
            {"name": "Cancelled Owner", "owner_type": "individual"},
        )
        await _pending(db, session_id, "cancel me", [cancel_call], cancel_id)
        cancelled = await cancel_pending_action(db, cancel_id)
        assert cancelled.pending_action and cancelled.pending_action.status == "cancelled"
        assert (
            await db.execute(select(Owner).where(Owner.name == "Cancelled Owner"))
        ).scalar_one_or_none() is None

        # A dependent failure rolls back earlier calls in the same confirmed plan.
        failure_id = uuid.uuid4()
        failure_owner_call, _ = _stage(
            failure_id,
            "create_owner",
            {"name": "Rollback Owner", "owner_type": "individual"},
        )
        failure_account_call, _ = _stage(
            failure_id,
            "create_account",
            {
                "name": "Broken Account",
                "owner_id": str(uuid.uuid4()),
                "institution_id": str(uuid.uuid4()),
                "account_type": "brokerage",
                "base_currency": "USD",
            },
        )
        await _pending(
            db,
            session_id,
            "must rollback",
            [failure_owner_call, failure_account_call],
            failure_id,
        )
        failed = await confirm_pending_action(db, failure_id)
        assert failed.pending_action and failed.pending_action.status == "failed"
        assert (
            await db.execute(select(Owner).where(Owner.name == "Rollback Owner"))
        ).scalar_one_or_none() is None

        # A transiently failed plan can be retried safely: the first attempt is
        # rolled back, the state hash is checked again, and reserved IDs remain
        # stable. A confirmed retry remains idempotent.
        retry_id = uuid.uuid4()
        retry_owner_call, retry_owner_preview = _stage(
            retry_id,
            "create_owner",
            {"name": "Retry Owner", "owner_type": "individual"},
        )
        retry_institution_call, retry_institution_preview = _stage(
            retry_id,
            "create_institution",
            {"name": "Retry Broker", "institution_type": "broker"},
        )
        await _pending(
            db,
            session_id,
            "retry transient plan",
            [retry_owner_call, retry_institution_call],
            retry_id,
        )

        original_dispatch_tool = agent_module.dispatch_tool
        fail_once = True

        async def flaky_dispatch_tool(db, name, args, *, commit=True):
            nonlocal fail_once
            if name == "create_institution" and fail_once:
                fail_once = False
                raise RuntimeError("transient_test_failure")
            return await original_dispatch_tool(db, name, args, commit=commit)

        agent_module.dispatch_tool = flaky_dispatch_tool
        try:
            first_attempt = await confirm_pending_action(db, retry_id)
            assert first_attempt.pending_action and first_attempt.pending_action.status == "failed"
            retry_owner_id = uuid.UUID(retry_owner_preview["reserved_id"])
            retry_institution_id = uuid.UUID(retry_institution_preview["reserved_id"])
            assert await db.get(Owner, retry_owner_id) is None
            assert await db.get(Institution, retry_institution_id) is None

            retried = await confirm_pending_action(db, retry_id)
            assert retried.pending_action and retried.pending_action.status == "confirmed"
            assert await db.get(Owner, retry_owner_id)
            assert await db.get(Institution, retry_institution_id)

            retried_again = await confirm_pending_action(db, retry_id)
            assert retried_again.pending_action and retried_again.pending_action.status == "confirmed"
            assert (
                int(
                    (
                        await db.execute(
                            select(func.count()).select_from(Owner).where(Owner.id == retry_owner_id)
                        )
                    ).scalar_one()
                )
                == 1
            )
        finally:
            agent_module.dispatch_tool = original_dispatch_tool

        # Failed retries still honor optimistic concurrency. If portfolio state
        # changes after the rollback, the old plan becomes stale instead of
        # replaying over newer data.
        stale_retry_id = uuid.uuid4()
        stale_owner_call, stale_owner_preview = _stage(
            stale_retry_id,
            "create_owner",
            {"name": "Stale Retry Owner", "owner_type": "individual"},
        )
        await _pending(
            db,
            session_id,
            "retry stale plan",
            [stale_owner_call],
            stale_retry_id,
        )

        async def always_fail_dispatch_tool(db, name, args, *, commit=True):
            raise RuntimeError("transient_test_failure")

        agent_module.dispatch_tool = always_fail_dispatch_tool
        try:
            stale_first_attempt = await confirm_pending_action(db, stale_retry_id)
            assert (
                stale_first_attempt.pending_action
                and stale_first_attempt.pending_action.status == "failed"
            )
        finally:
            agent_module.dispatch_tool = original_dispatch_tool

        stale_owner_id = uuid.UUID(stale_owner_preview["reserved_id"])
        external_owner = Owner(
            id=stale_owner_id,
            name="External Concurrent Change",
        )
        db.add(external_owner)
        await db.commit()
        stale_retry = await confirm_pending_action(db, stale_retry_id)
        assert stale_retry.pending_action and stale_retry.pending_action.status == "stale"
        assert await db.get(Owner, stale_owner_id) is external_owner
        await db.delete(external_owner)
        await db.commit()

        print(
            "agent_confirmation_ok staged=0 confirmed=9 idempotent=2 "
            "cancelled=1 rolled_back=3 compensation=2 retry=1 stale_retry=1"
        )


if __name__ == "__main__":
    asyncio.run(main())
