"""PostgreSQL smoke test for Phase 2–5 migrations and reversible ledger behavior.

Run against an empty migrated test database with:
    PYTHONPATH=. python tests/integration_smoke.py
"""

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.agent.state import capture_state, diff_states
from app.core.db import AsyncSessionLocal
from app.models import Account, AgentOperationLog, AgentSession, Institution, Instrument, Owner, Transaction
from app.models.enums import AssetClass, HoldingSource, MarketRegion, PriceSourceType
from app.schemas.transaction import BuyTransactionCreate, SellTransactionCreate, TransferCreate
from app.services import data_export_service, holding_service, transaction_service, undo_service


async def main() -> None:
    async with AsyncSessionLocal() as db:
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
        before = await capture_state(db)
        await holding_service.adjust_holding(db, account_id, instrument_id, Decimal("5"), HoldingSource.AGENT)
        after = await capture_state(db)
        before_diff, after_diff = diff_states(before, after)
        log = AgentOperationLog(
            session_id=session.id,
            turn_index=0,
            user_message="adjust test holding",
            operation_type="tool_call",
            description="integration undo",
            tool_calls_json=[],
            before_state_json=before_diff,
            after_state_json=after_diff,
        )
        db.add(log)
        await db.commit()
        await undo_service.undo_agent_operation(db, log.id)
        restored = await holding_service.get_holding(db, account_id, instrument_id)
        assert restored and restored.quantity == Decimal("10")

        json_backup = await data_export_service.export_json_bytes(db)
        csv_backup = await data_export_service.export_csv_zip_bytes(db)
        assert len(json_backup) > 100 and len(csv_backup) > 100
        account.name = "Changed after backup"
        await db.commit()
        restored_counts = await data_export_service.restore_json_bytes(db, json_backup)
        db.expire_all()
        restored_account = await db.get(Account, account_id)
        assert restored_account and restored_account.name == "Primary"
        assert restored_counts["transactions"] >= 3

        transactions = (await db.execute(select(Transaction))).scalars().all()
        print(
            f"integration_ok transactions={len(transactions)} "
            f"json={len(json_backup)} csv={len(csv_backup)} buy={buy_id}"
        )


if __name__ == "__main__":
    asyncio.run(main())
