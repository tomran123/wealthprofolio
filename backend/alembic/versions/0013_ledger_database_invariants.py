"""enforce ledger immutability and family-consistent relationships

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-28
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


# PostgreSQL requires the referenced column set of a composite foreign key to
# be unique. The UUID id remains the primary key; these redundant constraints
# make family ownership part of every relationship below.
FAMILY_REFERENCE_PARENTS = (
    "owners",
    "institutions",
    "exposure_groups",
    "accounts",
    "instruments",
    "transactions",
    "agent_sessions",
    "agent_messages",
    "agent_operation_logs",
    "documents",
    "document_versions",
    "document_pages",
    "document_extractions",
    "journal_entries",
)


# (child table, child id column, parent table, on-delete action, deferred)
#
# Polymorphic references such as document_links.target_id and
# background_jobs.resource_id cannot be represented by a relational FK and are
# intentionally absent. All concrete family-owned relationships are closed.
FAMILY_FOREIGN_KEYS = (
    ("accounts", "institution_id", "institutions", "RESTRICT", False),
    ("accounts", "owner_id", "owners", "RESTRICT", False),
    ("agent_messages", "session_id", "agent_sessions", "CASCADE", False),
    (
        "agent_operation_logs",
        "linked_to_id",
        "agent_operation_logs",
        "SET NULL",
        True,
    ),
    (
        "agent_operation_logs",
        "session_id",
        "agent_sessions",
        "CASCADE",
        False,
    ),
    (
        "agent_pending_actions",
        "assistant_message_id",
        "agent_messages",
        "SET NULL",
        False,
    ),
    (
        "agent_pending_actions",
        "session_id",
        "agent_sessions",
        "CASCADE",
        False,
    ),
    ("document_chunks", "document_id", "documents", "CASCADE", False),
    (
        "document_chunks",
        "document_version_id",
        "document_versions",
        "CASCADE",
        False,
    ),
    (
        "document_chunks",
        "document_page_id",
        "document_pages",
        "SET NULL",
        False,
    ),
    ("document_extractions", "document_id", "documents", "CASCADE", False),
    (
        "document_extractions",
        "document_version_id",
        "document_versions",
        "CASCADE",
        False,
    ),
    ("document_links", "document_id", "documents", "CASCADE", False),
    (
        "document_links",
        "extraction_id",
        "document_extractions",
        "SET NULL",
        False,
    ),
    ("document_pages", "document_id", "documents", "CASCADE", False),
    (
        "document_pages",
        "document_version_id",
        "document_versions",
        "CASCADE",
        False,
    ),
    ("document_versions", "document_id", "documents", "CASCADE", False),
    ("documents", "account_id", "accounts", "SET NULL", False),
    ("documents", "institution_id", "institutions", "SET NULL", False),
    ("documents", "owner_id", "owners", "SET NULL", False),
    ("holdings", "account_id", "accounts", "CASCADE", False),
    ("holdings", "instrument_id", "instruments", "RESTRICT", False),
    ("holdings", "last_event_id", "transactions", "SET NULL", True),
    (
        "instruments",
        "exposure_group_id",
        "exposure_groups",
        "SET NULL",
        False,
    ),
    (
        "journal_entries",
        "transaction_id",
        "transactions",
        "RESTRICT",
        True,
    ),
    (
        "journal_postings",
        "account_id",
        "accounts",
        "RESTRICT",
        False,
    ),
    (
        "journal_postings",
        "instrument_id",
        "instruments",
        "RESTRICT",
        False,
    ),
    (
        "journal_postings",
        "journal_entry_id",
        "journal_entries",
        "CASCADE",
        True,
    ),
    (
        "price_snapshots",
        "instrument_id",
        "instruments",
        "CASCADE",
        False,
    ),
    ("transactions", "account_id", "accounts", "RESTRICT", False),
    ("transactions", "instrument_id", "instruments", "RESTRICT", False),
    (
        "transactions",
        "linked_transaction_id",
        "transactions",
        "SET NULL",
        True,
    ),
    (
        "transactions",
        "reversed_by_id",
        "transactions",
        "SET NULL",
        True,
    ),
    (
        "transactions",
        "reversal_of_id",
        "transactions",
        "RESTRICT",
        True,
    ),
)


def _family_unique_name(table_name: str) -> str:
    return f"uq_{table_name}_family_id_id"


def _family_fk_name(table_name: str, column_name: str) -> str:
    return f"fk_{table_name}_family_{column_name}"


def _create_family_foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
    ondelete: str,
    deferred: bool,
) -> None:
    constraint_name = _family_fk_name(table_name, column_name)
    deferred_sql = " DEFERRABLE INITIALLY DEFERRED" if deferred else ""
    if ondelete == "SET NULL":
        # Without a column list PostgreSQL would also clear family_id, which is
        # NOT NULL and is the ownership boundary.
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ADD CONSTRAINT {constraint_name}
            FOREIGN KEY (family_id, {column_name})
            REFERENCES {referred_table} (family_id, id)
            ON DELETE SET NULL ({column_name}){deferred_sql}
            """
        )
        return
    op.create_foreign_key(
        constraint_name,
        table_name,
        referred_table,
        ["family_id", column_name],
        ["family_id", "id"],
        ondelete=ondelete,
        deferrable=deferred or None,
        initially="DEFERRED" if deferred else None,
    )


def _create_transaction_invariants() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM transactions AS reversal
                LEFT JOIN transactions AS original
                  ON original.family_id = reversal.family_id
                 AND original.id = reversal.reversal_of_id
                WHERE reversal.reversal_of_id IS NOT NULL
                  AND (
                      original.id IS NULL
                      OR original.is_reversed IS NOT TRUE
                      OR original.reversed_by_id IS DISTINCT FROM reversal.id
                      OR original.reversal_of_id IS NOT NULL
                      OR reversal.is_reversed IS NOT FALSE
                      OR reversal.reversed_by_id IS NOT NULL
                      OR reversal.account_id IS DISTINCT FROM original.account_id
                      OR reversal.instrument_id
                          IS DISTINCT FROM original.instrument_id
                      OR reversal.transaction_type
                          IS DISTINCT FROM original.transaction_type
                      OR reversal.quantity IS DISTINCT FROM -original.quantity
                      OR reversal.amount IS DISTINCT FROM -original.amount
                      OR reversal.fee IS DISTINCT FROM -original.fee
                      OR reversal.currency IS DISTINCT FROM original.currency
                      OR reversal.fee_currency
                          IS DISTINCT FROM original.fee_currency
                  )
            ) THEN
                RAISE EXCEPTION
                    '0013 cannot enable invariants: malformed reversal pair';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_transactions_family_reversal_once
        ON transactions (family_id, reversal_of_id)
        WHERE reversal_of_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_transaction_append_only() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.metadata_json ->> 'status' = 'draft'
                   AND OLD.is_reversed IS FALSE
                   AND OLD.reversed_by_id IS NULL
                   AND OLD.reversal_of_id IS NULL
                   AND NOT EXISTS (
                       SELECT 1
                       FROM journal_entries
                       WHERE family_id = OLD.family_id
                         AND transaction_id = OLD.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                       FROM audit_events
                       WHERE family_id = OLD.family_id
                         AND aggregate_type = 'transaction'
                         AND aggregate_id = OLD.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                       FROM outbox_events
                       WHERE family_id = OLD.family_id
                         AND aggregate_type = 'transaction'
                         AND aggregate_id = OLD.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                       FROM holdings
                       WHERE family_id = OLD.family_id
                         AND last_event_id = OLD.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                       FROM transactions AS dependent
                       WHERE dependent.family_id = OLD.family_id
                         AND (
                             dependent.linked_transaction_id = OLD.id
                             OR dependent.reversed_by_id = OLD.id
                             OR dependent.reversal_of_id = OLD.id
                         )
                   )
                THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'posted_transaction_is_append_only:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF (
                to_jsonb(NEW)
                    - ARRAY['is_reversed', 'reversed_by_id', 'updated_at']
            ) IS DISTINCT FROM (
                to_jsonb(OLD)
                    - ARRAY['is_reversed', 'reversed_by_id', 'updated_at']
            ) THEN
                RAISE EXCEPTION
                    'transaction_economic_fields_are_immutable:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.is_reversed IS NOT FALSE
               OR OLD.reversed_by_id IS NOT NULL
               OR OLD.reversal_of_id IS NOT NULL
               OR NEW.is_reversed IS NOT TRUE
               OR NEW.reversed_by_id IS NULL
            THEN
                RAISE EXCEPTION
                    'invalid_transaction_reversal_marker_transition:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM transactions AS reversal
                WHERE reversal.family_id = OLD.family_id
                  AND reversal.id = NEW.reversed_by_id
                  AND reversal.reversal_of_id = OLD.id
                  AND reversal.is_reversed IS FALSE
                  AND reversal.reversed_by_id IS NULL
                  AND reversal.account_id = OLD.account_id
                  AND reversal.instrument_id
                      IS NOT DISTINCT FROM OLD.instrument_id
                  AND reversal.transaction_type = OLD.transaction_type
                  AND reversal.quantity = -OLD.quantity
                  AND reversal.amount = -OLD.amount
                  AND reversal.fee = -OLD.fee
                  AND reversal.currency = OLD.currency
                  AND reversal.fee_currency = OLD.fee_currency
            ) THEN
                RAISE EXCEPTION 'invalid_transaction_reversal_pair:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER transactions_append_only_trigger
        BEFORE UPDATE OR DELETE ON transactions
        FOR EACH ROW EXECUTE FUNCTION enforce_transaction_append_only()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_reversal_pair_at_commit() RETURNS trigger AS $$
        BEGIN
            IF NEW.reversal_of_id IS NULL THEN
                RETURN NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM transactions AS original
                WHERE original.family_id = NEW.family_id
                  AND original.id = NEW.reversal_of_id
                  AND original.is_reversed IS TRUE
                  AND original.reversed_by_id = NEW.id
                  AND original.reversal_of_id IS NULL
                  AND NEW.is_reversed IS FALSE
                  AND NEW.reversed_by_id IS NULL
                  AND NEW.account_id = original.account_id
                  AND NEW.instrument_id
                      IS NOT DISTINCT FROM original.instrument_id
                  AND NEW.transaction_type = original.transaction_type
                  AND NEW.quantity = -original.quantity
                  AND NEW.amount = -original.amount
                  AND NEW.fee = -original.fee
                  AND NEW.currency = original.currency
                  AND NEW.fee_currency = original.fee_currency
            ) THEN
                RAISE EXCEPTION
                    'incomplete_transaction_reversal_pair:%', NEW.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transactions_reversal_pair_trigger
        AFTER INSERT ON transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_reversal_pair_at_commit()
        """
    )


def _replace_journal_invariants() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM journal_entries AS entry
                WHERE (
                    SELECT count(*)
                    FROM journal_postings AS posting
                    WHERE posting.journal_entry_id = entry.id
                ) < 2
            ) OR EXISTS (
                SELECT 1
                FROM journal_postings
                GROUP BY journal_entry_id, currency
                HAVING sum(debit) <> sum(credit)
            ) THEN
                RAISE EXCEPTION
                    '0013 cannot enable invariants: malformed journal entry';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER journal_postings_balance_trigger ON journal_postings"
    )
    op.execute("DROP FUNCTION enforce_journal_entry_balance()")
    op.execute(
        """
        CREATE FUNCTION assert_journal_entry_valid(
            target_entry uuid
        ) RETURNS void AS $$
        DECLARE
            posting_count integer;
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM journal_entries
                WHERE id = target_entry
            ) THEN
                RETURN;
            END IF;

            SELECT count(*) INTO posting_count
            FROM journal_postings
            WHERE journal_entry_id = target_entry;

            IF posting_count < 2 THEN
                RAISE EXCEPTION
                    'journal_entry_requires_two_postings:%', target_entry
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM journal_postings
                WHERE journal_entry_id = target_entry
                GROUP BY currency
                HAVING sum(debit) <> sum(credit)
            ) THEN
                RAISE EXCEPTION 'journal_entry_unbalanced:%', target_entry
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_journal_posting_invariants() RETURNS trigger AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                PERFORM assert_journal_entry_valid(OLD.journal_entry_id);
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE')
               AND (
                   TG_OP = 'INSERT'
                   OR NEW.journal_entry_id
                       IS DISTINCT FROM OLD.journal_entry_id
               )
            THEN
                PERFORM assert_journal_entry_valid(NEW.journal_entry_id);
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
        FOR EACH ROW EXECUTE FUNCTION enforce_journal_posting_invariants()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_journal_entry_has_postings() RETURNS trigger AS $$
        BEGIN
            PERFORM assert_journal_entry_valid(NEW.id);
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER journal_entry_has_postings_trigger
        AFTER INSERT OR UPDATE ON journal_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_journal_entry_has_postings()
        """
    )


def upgrade() -> None:
    # Alembic may apply 0012 and 0013 in one PostgreSQL transaction. Revision
    # 0012 inserts journal postings, which queues the deferred 0010 balance
    # trigger; PostgreSQL will not ALTER a referenced table while those events
    # are pending. The cutover has finished by this point, so settle all queued
    # checks before adding the stronger constraints.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    for table_name in FAMILY_REFERENCE_PARENTS:
        op.create_unique_constraint(
            _family_unique_name(table_name),
            table_name,
            ["family_id", "id"],
        )

    for relationship in FAMILY_FOREIGN_KEYS:
        _create_family_foreign_key(*relationship)

    _create_transaction_invariants()
    _replace_journal_invariants()


def _restore_legacy_journal_invariant() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_journal_entry_balance() RETURNS trigger AS $$
        DECLARE
            target_entry uuid;
            posting_count integer;
        BEGIN
            target_entry := COALESCE(
                NEW.journal_entry_id,
                OLD.journal_entry_id
            );
            SELECT count(*) INTO posting_count
            FROM journal_postings
            WHERE journal_entry_id = target_entry;
            IF posting_count > 0 AND posting_count < 2 THEN
                RAISE EXCEPTION
                    'journal_entry_requires_two_postings:%', target_entry;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM journal_postings
                WHERE journal_entry_id = target_entry
                GROUP BY currency
                HAVING sum(debit) <> sum(credit)
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
    op.execute(
        "DROP TRIGGER journal_entry_has_postings_trigger ON journal_entries"
    )
    op.execute(
        "DROP TRIGGER journal_postings_balance_trigger ON journal_postings"
    )
    op.execute("DROP FUNCTION enforce_journal_entry_has_postings()")
    op.execute("DROP FUNCTION enforce_journal_posting_invariants()")
    op.execute("DROP FUNCTION assert_journal_entry_valid(uuid)")
    _restore_legacy_journal_invariant()

    op.execute(
        "DROP TRIGGER transactions_reversal_pair_trigger ON transactions"
    )
    op.execute("DROP TRIGGER transactions_append_only_trigger ON transactions")
    op.execute("DROP FUNCTION enforce_reversal_pair_at_commit()")
    op.execute("DROP FUNCTION enforce_transaction_append_only()")
    op.drop_index(
        "uq_transactions_family_reversal_once",
        table_name="transactions",
    )

    for table_name, column_name, *_ in reversed(FAMILY_FOREIGN_KEYS):
        op.drop_constraint(
            _family_fk_name(table_name, column_name),
            table_name,
            type_="foreignkey",
        )

    for table_name in reversed(FAMILY_REFERENCE_PARENTS):
        op.drop_constraint(
            _family_unique_name(table_name),
            table_name,
            type_="unique",
        )

    # A multi-revision downgrade continues into 0012, which deletes journal
    # rows before 0010 drops the ledger tables. Keep the restored trigger's
    # declared default deferred for sessions that stop at 0012, while making it
    # immediate for the remainder of this migration transaction so PostgreSQL
    # does not retain trigger events that would block those later DDL steps.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
