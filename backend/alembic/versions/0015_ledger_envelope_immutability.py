"""make the transaction event envelope append-only and complete

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-28
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _create_append_only_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_immutable_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '%_is_append_only:%', TG_TABLE_NAME, OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("journal_entries", "journal_postings", "audit_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_append_only_trigger
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_immutable_ledger_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION enforce_outbox_delivery_only() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'outbox_event_is_append_only:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (
                to_jsonb(NEW)
                    - ARRAY['published_at', 'attempt_count', 'last_error']
            ) IS DISTINCT FROM (
                to_jsonb(OLD)
                    - ARRAY['published_at', 'attempt_count', 'last_error']
            ) THEN
                RAISE EXCEPTION 'outbox_payload_is_immutable:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.attempt_count < OLD.attempt_count THEN
                RAISE EXCEPTION 'outbox_attempt_count_must_be_monotonic:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.published_at IS NOT NULL
               AND NEW.published_at IS DISTINCT FROM OLD.published_at
            THEN
                RAISE EXCEPTION 'outbox_published_at_is_immutable:%', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER outbox_events_delivery_only_trigger
        BEFORE UPDATE OR DELETE ON outbox_events
        FOR EACH ROW EXECUTE FUNCTION enforce_outbox_delivery_only()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_transaction_metadata_projection_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'transaction_metadata_projection_cannot_be_deleted:%',
                    OLD.transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (
                to_jsonb(NEW)
                    - ARRAY[
                        'trade_date',
                        'executed_at',
                        'settlement_date',
                        'external_ref',
                        'note',
                        'version',
                        'last_event_id',
                        'updated_at'
                    ]
            ) IS DISTINCT FROM (
                to_jsonb(OLD)
                    - ARRAY[
                        'trade_date',
                        'executed_at',
                        'settlement_date',
                        'external_ref',
                        'note',
                        'version',
                        'last_event_id',
                        'updated_at'
                    ]
            ) THEN
                RAISE EXCEPTION
                    'transaction_metadata_projection_identity_is_immutable:%',
                    OLD.transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.version < OLD.version THEN
                RAISE EXCEPTION
                    'transaction_metadata_projection_version_must_be_monotonic:%',
                    OLD.transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER transaction_metadata_projection_guard_trigger
        BEFORE UPDATE OR DELETE ON transaction_metadata_projections
        FOR EACH ROW
        EXECUTE FUNCTION enforce_transaction_metadata_projection_mutation()
        """
    )


def _create_envelope_constraint() -> None:
    op.execute(
        """
        CREATE FUNCTION assert_transaction_event_envelope(
            target_family_id uuid,
            target_transaction_id uuid
        ) RETURNS void AS $$
        DECLARE
            transaction_status text;
        BEGIN
            SELECT metadata_json ->> 'status'
            INTO transaction_status
            FROM transactions
            WHERE family_id = target_family_id
              AND id = target_transaction_id;

            IF NOT FOUND OR transaction_status = 'draft' THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM transaction_metadata_projections
                WHERE family_id = target_family_id
                  AND transaction_id = target_transaction_id
            ) THEN
                RAISE EXCEPTION
                    'transaction_missing_metadata_projection:%',
                    target_transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM journal_entries
                WHERE family_id = target_family_id
                  AND transaction_id = target_transaction_id
            ) THEN
                RAISE EXCEPTION
                    'transaction_missing_journal_entry:%',
                    target_transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM audit_events
                WHERE family_id = target_family_id
                  AND aggregate_type = 'transaction'
                  AND aggregate_id = target_transaction_id
            ) THEN
                RAISE EXCEPTION
                    'transaction_missing_audit_event:%',
                    target_transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM outbox_events
                WHERE family_id = target_family_id
                  AND aggregate_type = 'transaction'
                  AND aggregate_id = target_transaction_id
            ) THEN
                RAISE EXCEPTION
                    'transaction_missing_outbox_event:%',
                    target_transaction_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_transaction_event_envelope() RETURNS trigger AS $$
        BEGIN
            PERFORM assert_transaction_event_envelope(NEW.family_id, NEW.id);
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transactions_event_envelope_trigger
        AFTER INSERT OR UPDATE ON transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transaction_event_envelope()
        """
    )

    # Refuse to enable the contract on a partially cut-over database.
    op.execute(
        """
        DO $$
        DECLARE
            candidate record;
        BEGIN
            FOR candidate IN
                SELECT family_id, id
                FROM transactions
            LOOP
                PERFORM assert_transaction_event_envelope(
                    candidate.family_id,
                    candidate.id
                );
            END LOOP;
        END;
        $$;
        """
    )


def _create_runtime_boundaries() -> None:
    op.execute(
        """
        CREATE FUNCTION wp_mark_transaction_reversed(
            p_family_id uuid,
            p_original_id uuid,
            p_reversal_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF p_original_id = p_reversal_id OR NOT EXISTS (
                SELECT 1
                FROM public.transactions AS reversal
                WHERE reversal.id = p_reversal_id
                  AND reversal.family_id = p_family_id
                  AND reversal.reversal_of_id = p_original_id
            ) THEN
                RAISE EXCEPTION 'invalid_transaction_reversal_pair';
            END IF;

            UPDATE public.transactions AS original
            SET is_reversed = true,
                reversed_by_id = p_reversal_id,
                updated_at = now()
            WHERE original.id = p_original_id
              AND original.family_id = p_family_id
              AND original.reversal_of_id IS NULL
              AND original.is_reversed = false
              AND original.reversed_by_id IS NULL;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'transaction_missing_or_already_reversed';
            END IF;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION wp_delete_draft_transaction(
            p_family_id uuid,
            p_transaction_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            DELETE FROM public.transactions AS target
            WHERE target.id = p_transaction_id
              AND target.family_id = p_family_id
              AND target.metadata_json ->> 'status' = 'draft';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'transaction_is_not_an_unposted_draft';
            END IF;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION wp_record_outbox_delivery(
            p_family_id uuid,
            p_event_id uuid,
            p_published_at timestamptz,
            p_last_error text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            UPDATE public.outbox_events AS event
            SET published_at = p_published_at,
                attempt_count = event.attempt_count + 1,
                last_error = p_last_error
            WHERE event.id = p_event_id
              AND event.family_id = p_family_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'outbox_event_not_found';
            END IF;
        END;
        $function$
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION
            wp_mark_transaction_reversed(uuid, uuid, uuid),
            wp_delete_draft_transaction(uuid, uuid),
            wp_record_outbox_delivery(uuid, uuid, timestamptz, text)
        FROM PUBLIC
        """
    )


def upgrade() -> None:
    _create_append_only_guards()
    _create_envelope_constraint()
    _create_runtime_boundaries()


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION wp_record_outbox_delivery(uuid, uuid, timestamptz, text)"
    )
    op.execute("DROP FUNCTION wp_delete_draft_transaction(uuid, uuid)")
    op.execute("DROP FUNCTION wp_mark_transaction_reversed(uuid, uuid, uuid)")

    op.execute(
        "DROP TRIGGER transactions_event_envelope_trigger ON transactions"
    )
    op.execute("DROP FUNCTION enforce_transaction_event_envelope()")
    op.execute("DROP FUNCTION assert_transaction_event_envelope(uuid, uuid)")

    op.execute(
        "DROP TRIGGER transaction_metadata_projection_guard_trigger "
        "ON transaction_metadata_projections"
    )
    op.execute("DROP FUNCTION enforce_transaction_metadata_projection_mutation()")

    op.execute(
        "DROP TRIGGER outbox_events_delivery_only_trigger ON outbox_events"
    )
    op.execute("DROP FUNCTION enforce_outbox_delivery_only()")

    for table_name in ("audit_events", "journal_postings", "journal_entries"):
        op.execute(
            f"DROP TRIGGER {table_name}_append_only_trigger ON {table_name}"
        )
    op.execute("DROP FUNCTION reject_immutable_ledger_mutation()")
