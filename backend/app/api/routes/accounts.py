import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Account
from app.models.enums import PriceSourceType
from app.schemas.account import AccountCreate, AccountUpdate, AccountWithNames
from app.schemas.holding import HoldingWithInstrument
from app.services import account_service, holding_service, valuation_service

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(get_current_user)])


def _to_schema(account: Account) -> AccountWithNames:
    return AccountWithNames(
        id=account.id,
        institution_id=account.institution_id,
        owner_id=account.owner_id,
        name=account.name,
        account_type=account.account_type,
        base_currency=account.base_currency,
        account_number_mask=account.account_number_mask,
        institution_name=account.institution.name,
        owner_name=account.owner.name,
    )


@router.get("", response_model=list[AccountWithNames])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    accounts = await account_service.list_accounts(db)
    return [_to_schema(a) for a in accounts]


@router.get("/{account_id}", response_model=AccountWithNames)
async def get_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await account_service.get_account(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    return _to_schema(account)


@router.post("", response_model=AccountWithNames, status_code=status.HTTP_201_CREATED)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db)):
    account = await account_service.create_account(db, payload)
    return _to_schema(account)


@router.patch("/{account_id}", response_model=AccountWithNames)
async def update_account(account_id: uuid.UUID, payload: AccountUpdate, db: AsyncSession = Depends(get_db)):
    account = await account_service.update_account(db, account_id, payload)
    if account is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    return _to_schema(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await account_service.delete_account(db, account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="account_not_found")


@router.get("/{account_id}/holdings", response_model=list[HoldingWithInstrument])
async def list_account_holdings(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    holdings = await holding_service.list_holdings_for_account(db, account_id)
    snapshots = await valuation_service.get_latest_prices(
        db,
        (holding.instrument_id for holding in holdings),
    )
    result: list[HoldingWithInstrument] = []
    for holding in holdings:
        snapshot = snapshots.get(holding.instrument_id)
        price = snapshot.price if snapshot else None
        price_currency = snapshot.currency if snapshot else None
        quote_status: str | None = None
        price_as_of = snapshot.as_of.isoformat() if snapshot else None
        if snapshot is not None:
            quote_status = (
                snapshot.quote_status.value
                if hasattr(snapshot.quote_status, "value")
                else str(snapshot.quote_status)
            )
        elif holding.instrument.price_source_type in (
            PriceSourceType.FX_DERIVED,
            PriceSourceType.FIXED_PRINCIPAL,
        ):
            price = Decimal("1")
            price_currency = holding.instrument.currency
            quote_status = "fixed"
        result.append(
            HoldingWithInstrument(
                id=holding.id,
                account_id=holding.account_id,
                instrument_id=holding.instrument_id,
                quantity=holding.quantity,
                source=holding.source,
                instrument_name=holding.instrument.name,
                instrument_symbol=holding.instrument.symbol,
                price_source_type=holding.instrument.price_source_type,
                price=price,
                price_currency=price_currency,
                market_value=holding.quantity * price if price is not None else None,
                quote_status=quote_status,
                price_as_of=price_as_of,
            )
        )
    return result
