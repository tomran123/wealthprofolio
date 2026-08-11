"""project effective non-economic transaction metadata

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transaction_metadata_projections",
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_date", sa.Date(), nullable=True),
        sa.Column("external_ref", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "last_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "family_id",
            "transaction_id",
            name="uq_transaction_metadata_projection_family_transaction",
        ),
    )
    op.create_index(
        "ix_transaction_metadata_projections_family_id",
        "transaction_metadata_projections",
        ["family_id"],
    )
    op.create_index(
        "ix_transaction_metadata_projections_trade_date",
        "transaction_metadata_projections",
        ["trade_date"],
    )
    op.create_index(
        "ix_transaction_metadata_projections_last_event_id",
        "transaction_metadata_projections",
        ["last_event_id"],
    )
    op.create_foreign_key(
        "fk_transaction_metadata_projection_transaction_family",
        "transaction_metadata_projections",
        "transactions",
        ["family_id", "transaction_id"],
        ["family_id", "id"],
        ondelete="CASCADE",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_transaction_metadata_projection_last_event_family",
        "transaction_metadata_projections",
        "transactions",
        ["family_id", "last_event_id"],
        ["family_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        """
        INSERT INTO transaction_metadata_projections (
            transaction_id,
            family_id,
            trade_date,
            executed_at,
            settlement_date,
            external_ref,
            note,
            version,
            last_event_id,
            created_at,
            updated_at
        )
        SELECT
            id,
            family_id,
            trade_date,
            executed_at,
            settlement_date,
            external_ref,
            note,
            1,
            id,
            created_at,
            updated_at
        FROM transactions
        """
    )
    # Apply any amendments produced between 0010 and this deployment in event
    # order. JSON null explicitly clears nullable projection fields.
    op.execute(
        """
        DO $$
        DECLARE
            amendment record;
            changes jsonb;
            target_transaction_id uuid;
        BEGIN
            FOR amendment IN
                SELECT id, family_id, metadata_json, created_at
                FROM transactions
                WHERE transaction_type = 'metadata_amended'
                  AND metadata_json ? 'amends_transaction_id'
                ORDER BY created_at, id
            LOOP
                target_transaction_id :=
                    (amendment.metadata_json ->> 'amends_transaction_id')::uuid;
                changes := COALESCE(
                    amendment.metadata_json -> 'changes',
                    '{}'::jsonb
                );
                UPDATE transaction_metadata_projections
                SET trade_date = CASE
                        WHEN changes ? 'trade_date'
                            THEN (changes ->> 'trade_date')::date
                        ELSE trade_date
                    END,
                    executed_at = CASE
                        WHEN changes ? 'executed_at'
                            THEN NULLIF(changes ->> 'executed_at', '')::timestamptz
                        ELSE executed_at
                    END,
                    settlement_date = CASE
                        WHEN changes ? 'settlement_date'
                            THEN NULLIF(changes ->> 'settlement_date', '')::date
                        ELSE settlement_date
                    END,
                    external_ref = CASE
                        WHEN changes ? 'external_ref'
                            THEN changes ->> 'external_ref'
                        ELSE external_ref
                    END,
                    note = CASE
                        WHEN changes ? 'note'
                            THEN changes ->> 'note'
                        ELSE note
                    END,
                    version = version + 1,
                    last_event_id = amendment.id,
                    updated_at = amendment.created_at
                WHERE family_id = amendment.family_id
                  AND transaction_id = target_transaction_id;
            END LOOP;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("transaction_metadata_projections")
