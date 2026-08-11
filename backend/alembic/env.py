import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models import Base  # noqa: F401  (ensures all models are registered on Base.metadata)

config = context.config
database_url = os.environ.get("DATABASE_URL") or config.get_main_option(
    "sqlalchemy.url"
)
if not database_url:
    raise RuntimeError("DATABASE_URL is required for Alembic migrations")
# Alembic stores this value in a ConfigParser, where percent signs introduce
# interpolation. Production passwords must be URL encoded (for example
# ``%40`` for ``@``), so escape percent signs for ConfigParser; reading the
# option restores the exact SQLAlchemy URL.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


MIGRATION_MANAGED_INDEXES = {
    # PostgreSQL-specific expression/operator-class indexes are intentionally
    # created in reviewed migrations rather than portable ORM declarations.
    "ix_document_chunks_embedding_hnsw",
    "ix_document_chunks_search_vector",
    "uq_instruments_family_market_provider",
    "uq_instruments_family_market_symbol",
    "uq_transactions_family_reversal_once",
}


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Keep Alembic useful without proposing removal of DB-only invariants."""

    if not reflected or compare_to is not None:
        return True
    if type_ == "index" and name in MIGRATION_MANAGED_INDEXES:
        return False
    if type_ == "unique_constraint":
        column_names = {column.name for column in object_.columns}
        if column_names == {"family_id", "id"}:
            return False
    if type_ == "foreign_key_constraint" and len(object_.columns) > 1:
        # 0013 closes cross-family ID substitution with composite ownership
        # FKs. Most tables retain their original scalar FK as the ORM join
        # hint, while PostgreSQL owns the stronger composite invariant.
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
