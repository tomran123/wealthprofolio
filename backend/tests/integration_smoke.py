"""PostgreSQL smoke test for family-scoped, reversible ledger behavior.

Run against the dedicated, empty migrated test database with:
    DATABASE_URL=postgresql+asyncpg://...@127.0.0.1:64236/codex_legacy_smoke_20260728 \
      PYTHONPATH=. python tests/integration_smoke.py
"""

# The disposable-target guard intentionally runs before importing application
# modules, because those modules construct the database engine at import time.
# ruff: noqa: E402

import asyncio
import os
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import unquote, urlsplit

from sqlalchemy import select

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

from app.core.db import AsyncSessionLocal
from app.core.family_scope import RequestContext, bind_request_context
from app.agent.agent import _transaction_event_ids
from app.agent.state import json_value
from app.models import (
    Account,
    AgentOperationLog,
    AgentSession,
    Family,
    FamilyMembership,
    Institution,
    Instrument,
    Owner,
    Transaction,
    TransactionMetadataProjection,
    User,
)
from app.models.enums import (
    AssetClass,
    HoldingSource,
    MarketRegion,
    PriceSourceType,
    TransactionType,
)
from app.schemas.transaction import (
    BuyTransactionCreate,
    CashTransactionCreate,
    SellTransactionCreate,
    TransactionMetadataUpdate,
    TransferCreate,
)
from app.services import data_export_service, holding_service, transaction_service, undo_service
from app.services.auth_service import ensure_initial_user


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
        owner = Owner(name="Integration Owner")
        institution = Institution(name="Integration Broker")
        db.add_all([owner, institution])
        await db.flush()
        account = Account(name="Primary", owner_id=owner.id, institution_id=institution.id, base_currency="USD")
        account2 = Account(name="Secondary", owner_id=owner.id, institution_id=institution.id, base_currency="USD")
        instrument = Instrument(
            name="Integration ETF",
            symbol="TEST",
            asset_class=AssetClass.ETF,
            currency="USD",
            market=MarketRegion.US,
            price_source_type=PriceSourceType.MARKET,
        )
        db.add_all([account, account2, instrument])
        await db.commit()
        account_id = account.id
        account2_id = account2.id
        instrument_id = instrument.id

        await transaction_service.create_cash_transaction(
            db,
            CashTransactionCreate(
                account_id=account_id,
                amount=Decimal("2000"),
                currency="USD",
                transaction_type=TransactionType.DEPOSIT,
                trade_date=date.today(),
            ),
            idempotency_key="legacy-smoke:seed-cash",
        )
        buy = await transaction_service.create_buy_transaction(
            db,
            BuyTransactionCreate(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("10"),
                price=Decimal("100"),
                currency="USD",
                fee=Decimal("1"),
                trade_date=date.today(),
            ),
        )
        buy_id = buy.id
        sell = await transaction_service.create_sell_transaction(
            db,
            SellTransactionCreate(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("4"),
                price=Decimal("120"),
                currency="USD",
                fee=Decimal("2"),
                trade_date=date.today(),
            ),
        )
        holding = await holding_service.get_holding(db, account_id, instrument_id)
        assert holding and holding.quantity == Decimal("6")
        await transaction_service.reverse_transaction(db, sell.id)
        holding = await holding_service.get_holding(db, account_id, instrument_id)
        assert holding and holding.quantity == Decimal("10")

        transfer = await transaction_service.create_transfer(
            db,
            TransferCreate(
                from_account_id=account_id,
                to_account_id=account2_id,
                instrument_id=instrument_id,
                quantity=Decimal("2"),
                currency="USD",
                trade_date=date.today(),
            ),
        )
        await transaction_service.delete_transaction(db, transfer[0].id)
        primary = await holding_service.get_holding(db, account_id, instrument_id)
        secondary = await holding_service.get_holding(db, account2_id, instrument_id)
        assert primary and primary.quantity == Decimal("10")
        assert secondary and secondary.quantity == Decimal("0")

        session = AgentSession(title="Undo integration")
        db.add(session)
        await db.commit()
        await holding_service.adjust_holding(
            db,
            account_id,
            instrument_id,
            Decimal("5"),
            HoldingSource.AGENT,
            idempotency_key="legacy-smoke:agent-adjust",
        )
        adjustment = (
            await db.execute(
                select(Transaction).where(
                    Transaction.idempotency_key == "legacy-smoke:agent-adjust"
                )
            )
        ).scalar_one()
        log = AgentOperationLog(
            session_id=session.id,
            turn_index=0,
            user_message="adjust test holding",
            operation_type="tool_call",
            description="integration undo",
            tool_calls_json=[],
            before_state_json={},
            after_state_json={},
            event_ids_json=[str(adjustment.id)],
            summary_json={"event_count": 1},
        )
        db.add(log)
        await db.commit()
        await undo_service.undo_agent_operation(db, log.id)
        restored = await holding_service.get_holding(db, account_id, instrument_id)
        assert restored and restored.quantity == Decimal("10")

        # Metadata amendment undo restores only the metadata projection. It
        # must never mistake causation/amends UUID references for the original
        # economic transaction and reverse the purchase.
        amendment = (
            await transaction_service.update_transaction_metadata(
                db,
                buy.id,
                TransactionMetadataUpdate(note="temporary Agent note"),
                idempotency_key="legacy-smoke:metadata-amendment",
            )
        )[0]
        assert await _transaction_event_ids(db, json_value(amendment)) == [
            str(amendment.id)
        ]
        metadata_log = AgentOperationLog(
            session_id=session.id,
            turn_index=1,
            user_message="temporarily amend buy note",
            operation_type="tool_call",
            description="metadata compensation integration",
            tool_calls_json=[
                {
                    "tool": "update_transaction_metadata",
                    "event_ids": [str(amendment.id)],
                }
            ],
            before_state_json={},
            after_state_json={},
            event_ids_json=[str(amendment.id)],
            summary_json={
                "event_count": 1,
                "event_order": "tool_execution_v1",
                "compensatable": True,
            },
        )
        db.add(metadata_log)
        await db.commit()
        await undo_service.undo_agent_operation(db, metadata_log.id)
        await db.refresh(buy)
        await db.refresh(amendment)
        metadata_projection = await db.get(TransactionMetadataProjection, buy_id)
        assert metadata_projection and metadata_projection.note is None
        assert not buy.is_reversed
        assert amendment.is_reversed
        after_metadata_undo = await holding_service.get_holding(
            db,
            account_id,
            instrument_id,
        )
        assert after_metadata_undo and after_metadata_undo.quantity == Decimal("10")

        stale_amendment = (
            await transaction_service.update_transaction_metadata(
                db,
                buy.id,
                TransactionMetadataUpdate(note="older metadata value"),
                idempotency_key="legacy-smoke:metadata-stale",
            )
        )[0]
        await transaction_service.update_transaction_metadata(
            db,
            buy.id,
            TransactionMetadataUpdate(note="newer metadata value"),
            idempotency_key="legacy-smoke:metadata-newer",
        )
        stale_log = AgentOperationLog(
            session_id=session.id,
            turn_index=2,
            user_message="stale metadata undo",
            operation_type="tool_call",
            description="must not overwrite newer metadata",
            tool_calls_json=[
                {
                    "tool": "update_transaction_metadata",
                    "event_ids": [str(stale_amendment.id)],
                }
            ],
            before_state_json={},
            after_state_json={},
            event_ids_json=[str(stale_amendment.id)],
            summary_json={
                "event_count": 1,
                "event_order": "tool_execution_v1",
                "compensatable": True,
            },
        )
        db.add(stale_log)
        await db.commit()
        try:
            await undo_service.undo_agent_operation(db, stale_log.id)
        except ValueError as exc:
            assert str(exc) == "transaction_metadata_changed_after_amendment"
        else:
            raise AssertionError("stale_metadata_undo_must_fail_closed")
        metadata_projection = await db.get(TransactionMetadataProjection, buy_id)
        await db.refresh(metadata_projection)
        await db.refresh(buy)
        assert metadata_projection.note == "newer metadata value"
        assert not buy.is_reversed

        json_backup = await data_export_service.export_json_bytes(db)
        csv_backup = await data_export_service.export_csv_zip_bytes(db)
        assert len(json_backup) > 100 and len(csv_backup) > 100
        account.name = "Changed after backup"
        await db.commit()
        try:
            await data_export_service.restore_json_bytes(db, json_backup)
        except ValueError as exc:
            assert str(exc) == "family_restore_requires_empty_ledger"
        else:
            raise AssertionError("live_ledger_restore_must_be_rejected")
        await db.refresh(account)
        assert account.name == "Changed after backup"

        transactions = (await db.execute(select(Transaction))).scalars().all()
        print(
            f"integration_ok transactions={len(transactions)} "
            f"json={len(json_backup)} csv={len(csv_backup)} buy={buy_id} "
            "restore=live_ledger_rejected"
        )


if __name__ == "__main__":
    asyncio.run(main())
