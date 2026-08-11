"""add portfolio valuation snapshots

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-21
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "valuation_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("total_assets", sa.Numeric(24, 2), nullable=False),
        sa.Column("total_liabilities", sa.Numeric(24, 2), nullable=False),
        sa.Column("net_worth", sa.Numeric(24, 2), nullable=False),
        sa.Column("allocation_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "refresh_result_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.create_index("ix_valuation_snapshots_created_at", "valuation_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_valuation_snapshots_created_at", table_name="valuation_snapshots")
    op.drop_table("valuation_snapshots")
