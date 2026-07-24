"""add transaction ledger

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-21
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("price", sa.Numeric(24, 6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(24, 2), nullable=False, server_default="0"),
        sa.Column("fee", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("fee_currency", sa.String(length=3), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=True),
        sa.Column("external_ref", sa.String(length=100), nullable=True),
        sa.Column("linked_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("is_reversed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reversed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["linked_transaction_id"],
            ["transactions.id"],
            name="fk_transactions_linked_transaction_id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["reversed_by_id"],
            ["transactions.id"],
            name="fk_transactions_reversed_by_id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index("ix_transactions_account_id", "transactions", ["account_id"])
    op.create_index("ix_transactions_instrument_id", "transactions", ["instrument_id"])
    op.create_index("ix_transactions_transaction_type", "transactions", ["transaction_type"])
    op.create_index("ix_transactions_trade_date", "transactions", ["trade_date"])


def downgrade() -> None:
    op.drop_index("ix_transactions_trade_date", table_name="transactions")
    op.drop_index("ix_transactions_transaction_type", table_name="transactions")
    op.drop_index("ix_transactions_instrument_id", table_name="transactions")
    op.drop_index("ix_transactions_account_id", table_name="transactions")
    op.drop_table("transactions")
