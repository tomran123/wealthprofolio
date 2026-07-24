import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Account
from app.schemas.account import AccountCreate, AccountUpdate


async def list_accounts(db: AsyncSession) -> list[Account]:
    stmt = (
        select(Account)
        .options(selectinload(Account.institution), selectinload(Account.owner))
        .order_by(Account.name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_account(db: AsyncSession, account_id: uuid.UUID) -> Account | None:
    stmt = (
        select(Account)
        .where(Account.id == account_id)
        .options(selectinload(Account.institution), selectinload(Account.owner))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_account(
    db: AsyncSession,
    data: AccountCreate,
    *,
    record_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Account:
    values = data.model_dump()
    if record_id is not None:
        values["id"] = record_id
    account = Account(**values)
    db.add(account)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return await get_account(db, account.id)  # type: ignore[return-value]


async def update_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    data: AccountUpdate,
    *,
    commit: bool = True,
) -> Account | None:
    account = await db.get(Account, account_id)
    if account is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return await get_account(db, account_id)


async def delete_account(db: AsyncSession, account_id: uuid.UUID, *, commit: bool = True) -> bool:
    account = await db.get(Account, account_id)
    if account is None:
        return False
    await db.delete(account)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True
