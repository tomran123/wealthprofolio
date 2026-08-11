"""add valuation lookup performance indexes

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-23
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_price_snapshots_instrument_as_of",
        "price_snapshots",
        ["instrument_id", "as_of", "fetched_at"],
    )
    op.create_index(
        "ix_fx_rate_snapshots_pair_as_of",
        "fx_rate_snapshots",
        ["base_currency", "quote_currency", "as_of", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fx_rate_snapshots_pair_as_of",
        table_name="fx_rate_snapshots",
    )
    op.drop_index(
        "ix_price_snapshots_instrument_as_of",
        table_name="price_snapshots",
    )