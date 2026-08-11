"""add family boundary and transactional event ledger

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-24
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

DEFAULT_FAMILY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
FAMILY_OWNED_TABLES = (
    "owners",
    "institutions",
    "accounts",
    "instruments",
    "exposure_groups",
    "transactions",
    "holdings",
    "valuation_snapshots",
    "import_batches",
    "agent_sessions",
    "agent_messages",
    "agent_operation_logs",
    "agent_pending_actions",
    "llm_provider_configs",
    "price_snapshots",
)


def _add_family_column(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        f"fk_{table_name}_family_id",
        table_name,
        "families",
        ["family_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    # Expand: create the boundary without changing any pre-existing revision.
    op.add_column(
        "users",
        sa.Column("is_system_admin", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE users SET is_system_admin = false WHERE is_system_admin IS NULL")
    # The legacy application had no platform role. Preserve one recovery
    # administrator deterministically instead of escalating every legacy user.
    op.execute(
        """
        UPDATE users
        SET is_system_admin = true
        WHERE id = (
            SELECT id FROM users ORDER BY created_at, id LIMIT 1
        )
        """
    )
    op.alter_column(
        "users",
        "is_system_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )
    op.create_table(
        "families",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.UniqueConstraint("slug", name="uq_families_slug"),
    )
    op.create_index("ix_families_slug", "families", ["slug"])
    op.execute(
        sa.text(
            """
            INSERT INTO families (id, name, slug)
            VALUES (:id, 'Default Family', 'default-family')
            """
        ).bindparams(
            sa.bindparam(
                "id",
                value=DEFAULT_FAMILY_ID,
                type_=postgresql.UUID(as_uuid=True),
            )
        )
    )

    op.create_table(
        "family_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "family_id",
            "user_id",
            name="uq_family_membership_family_user",
        ),
    )
    op.create_index("ix_family_memberships_family_id", "family_memberships", ["family_id"])
    op.create_index("ix_family_memberships_user_id", "family_memberships", ["user_id"])
    op.execute(
        sa.text(
            """
            INSERT INTO family_memberships
                (id, family_id, user_id, role, is_active)
            SELECT
                md5(id::text || '-default-family')::uuid,
                :family_id,
                id,
                CASE
                    WHEN is_system_admin THEN 'admin'
                    ELSE 'member'
                END,
                true
            FROM users
            """
        ).bindparams(
            sa.bindparam(
                "family_id",
                value=DEFAULT_FAMILY_ID,
                type_=postgresql.UUID(as_uuid=True),
            )
        )
    )

    for table_name in FAMILY_OWNED_TABLES:
        _add_family_column(table_name)
    _add_family_column("app_settings")

    # Backfill: parent-derived ownership where possible, default ownership for
    # legacy root aggregates, then index and contract to NOT NULL.
    for table_name in (
        "owners",
        "institutions",
        "instruments",
        "exposure_groups",
        "valuation_snapshots",
        "import_batches",
        "agent_sessions",
        "llm_provider_configs",
        "app_settings",
    ):
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET family_id = :family_id WHERE family_id IS NULL"
            ).bindparams(
                sa.bindparam(
                    "family_id",
                    value=DEFAULT_FAMILY_ID,
                    type_=postgresql.UUID(as_uuid=True),
                )
            )
        )
    op.execute(
        """
        UPDATE accounts AS child
        SET family_id = parent.family_id
        FROM owners AS parent
        WHERE child.owner_id = parent.id AND child.family_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE transactions AS child
        SET family_id = parent.family_id
        FROM accounts AS parent
        WHERE child.account_id = parent.id AND child.family_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE holdings AS child
        SET family_id = parent.family_id
        FROM accounts AS parent
        WHERE child.account_id = parent.id AND child.family_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE price_snapshots AS child
        SET family_id = parent.family_id
        FROM instruments AS parent
        WHERE child.instrument_id = parent.id AND child.family_id IS NULL
        """
    )
    for child in ("agent_messages", "agent_operation_logs", "agent_pending_actions"):
        op.execute(
            f"""
            UPDATE {child} AS child
            SET family_id = parent.family_id
            FROM agent_sessions AS parent
            WHERE child.session_id = parent.id AND child.family_id IS NULL
            """
        )

    for table_name in FAMILY_OWNED_TABLES + ("app_settings",):
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET family_id = :family_id WHERE family_id IS NULL"
            ).bindparams(
                sa.bindparam(
                    "family_id",
                    value=DEFAULT_FAMILY_ID,
                    type_=postgresql.UUID(as_uuid=True),
                )
            )
        )
        op.create_index(f"ix_{table_name}_family_id", table_name, ["family_id"])
        op.alter_column(
            table_name,
            "family_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )

    # Existing globally unique settings/groups become family-local.
    op.drop_constraint("uq_exposure_groups_name", "exposure_groups", type_="unique")
    op.create_unique_constraint(
        "uq_exposure_groups_family_name",
        "exposure_groups",
        ["family_id", "name"],
    )
    op.drop_constraint("app_settings_pkey", "app_settings", type_="primary")
    op.create_primary_key("app_settings_pkey", "app_settings", ["family_id", "key"])

    # Transaction event envelope and holding projection cursor.
    op.add_column(
        "transactions",
        sa.Column("event_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("reversal_of_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_transactions_created_by_user_id",
        "transactions",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_transactions_reversal_of_id",
        "transactions",
        "transactions",
        ["reversal_of_id"],
        ["id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute(
        """
        UPDATE transactions
        SET event_version = 1,
            idempotency_key = 'legacy:' || id::text,
            correlation_id = id,
            metadata_json = '{}'::jsonb
        """
    )
    # Legacy linked/reversal rows use deferred self-referential FKs. PostgreSQL
    # will not ALTER this table while validation events from the backfill are
    # pending, even though the referenced columns did not change.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    for column_name, column_type in (
        ("event_version", sa.Integer()),
        ("idempotency_key", sa.String(length=200)),
        ("correlation_id", postgresql.UUID(as_uuid=True)),
        ("metadata_json", postgresql.JSONB()),
    ):
        op.alter_column(
            "transactions",
            column_name,
            existing_type=column_type,
            nullable=False,
        )
    op.execute("SET CONSTRAINTS ALL DEFERRED")
    op.create_unique_constraint(
        "uq_transaction_family_idempotency",
        "transactions",
        ["family_id", "idempotency_key"],
    )
    op.create_index("ix_transactions_correlation_id", "transactions", ["correlation_id"])

    op.add_column(
        "holdings",
        sa.Column("projection_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "holdings",
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_holdings_last_event_id",
        "holdings",
        "transactions",
        ["last_event_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Ledger, audit, and outbox are written in the same PostgreSQL transaction.
    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint(
            "family_id",
            "transaction_id",
            name="uq_journal_entry_family_transaction",
        ),
    )
    op.create_index("ix_journal_entries_family_id", "journal_entries", ["family_id"])
    op.create_index("ix_journal_entries_transaction_id", "journal_entries", ["transaction_id"])
    op.create_index("ix_journal_entries_correlation_id", "journal_entries", ["correlation_id"])

    op.create_table(
        "journal_postings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "journal_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_code", sa.String(length=160), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("debit", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(24, 6), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Numeric(24, 6), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("debit >= 0", name="ck_journal_posting_debit_nonnegative"),
        sa.CheckConstraint("credit >= 0", name="ck_journal_posting_credit_nonnegative"),
        sa.CheckConstraint(
            "NOT (debit > 0 AND credit > 0)",
            name="ck_journal_posting_single_side",
        ),
    )
    op.create_index("ix_journal_postings_family_id", "journal_postings", ["family_id"])
    op.create_index("ix_journal_postings_journal_entry_id", "journal_postings", ["journal_entry_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "summary_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    for column in ("family_id", "occurred_at", "action", "aggregate_id", "correlation_id"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "family_id",
            "idempotency_key",
            name="uq_outbox_family_idempotency",
        ),
    )
    for column in (
        "family_id",
        "occurred_at",
        "aggregate_id",
        "event_type",
        "correlation_id",
    ):
        op.create_index(f"ix_outbox_events_{column}", "outbox_events", [column])

    # Cross-row balance is a database invariant, checked at transaction commit.
    op.execute(
        """
        CREATE FUNCTION enforce_journal_entry_balance() RETURNS trigger AS $$
        DECLARE
            target_entry uuid;
            posting_count integer;
        BEGIN
            target_entry := COALESCE(NEW.journal_entry_id, OLD.journal_entry_id);
            SELECT COUNT(*) INTO posting_count
            FROM journal_postings
            WHERE journal_entry_id = target_entry;
            IF posting_count > 0 AND posting_count < 2 THEN
                RAISE EXCEPTION 'journal_entry_requires_two_postings:%', target_entry;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM journal_postings
                WHERE journal_entry_id = target_entry
                GROUP BY currency
                HAVING SUM(debit) <> SUM(credit)
            ) THEN
                RAISE EXCEPTION 'journal_entry_unbalanced:%', target_entry;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER journal_postings_balance_trigger
        AFTER INSERT OR UPDATE OR DELETE ON journal_postings
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_journal_entry_balance()
        """
    )


def downgrade() -> None:
    family_count = int(
        op.get_bind().execute(sa.text("SELECT COUNT(*) FROM families")).scalar_one()
    )
    if family_count > 1:
        raise RuntimeError(
            "0010 downgrade is intentionally blocked when multiple families exist; "
            "removing family_id cannot preserve overlapping family-local keys"
        )
    op.execute("DROP TRIGGER IF EXISTS journal_postings_balance_trigger ON journal_postings")
    op.execute("DROP FUNCTION IF EXISTS enforce_journal_entry_balance()")
    op.drop_table("outbox_events")
    op.drop_table("audit_events")
    op.drop_table("journal_postings")
    op.drop_table("journal_entries")

    op.drop_constraint("fk_holdings_last_event_id", "holdings", type_="foreignkey")
    op.drop_column("holdings", "last_event_id")
    op.drop_column("holdings", "projection_version")

    op.drop_index("ix_transactions_correlation_id", table_name="transactions")
    op.drop_constraint("uq_transaction_family_idempotency", "transactions", type_="unique")
    op.drop_constraint("fk_transactions_reversal_of_id", "transactions", type_="foreignkey")
    op.drop_constraint("fk_transactions_created_by_user_id", "transactions", type_="foreignkey")
    for column in (
        "reversal_of_id",
        "metadata_json",
        "created_by_user_id",
        "causation_id",
        "correlation_id",
        "idempotency_key",
        "event_version",
    ):
        op.drop_column("transactions", column)

    op.drop_constraint("app_settings_pkey", "app_settings", type_="primary")
    op.create_primary_key("app_settings_pkey", "app_settings", ["key"])
    op.drop_constraint("uq_exposure_groups_family_name", "exposure_groups", type_="unique")
    op.create_unique_constraint("uq_exposure_groups_name", "exposure_groups", ["name"])

    for table_name in reversed(FAMILY_OWNED_TABLES + ("app_settings",)):
        op.drop_index(f"ix_{table_name}_family_id", table_name=table_name)
        op.drop_constraint(f"fk_{table_name}_family_id", table_name, type_="foreignkey")
        op.drop_column(table_name, "family_id")
    op.drop_table("family_memberships")
    op.drop_index("ix_families_slug", table_name="families")
    op.drop_table("families")
    op.drop_column("users", "is_system_admin")
