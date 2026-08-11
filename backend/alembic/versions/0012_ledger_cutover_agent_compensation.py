"""cut legacy holdings over to replayable events and remove agent snapshots

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agent confirmations now compare only the rows/resources a plan will
    # mutate. Operation history stores event references and a redacted summary;
    # full before/after database snapshots are intentionally retired.
    op.add_column(
        "agent_pending_actions",
        sa.Column(
            "expected_versions_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "agent_operation_logs",
        sa.Column(
            "event_ids_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "agent_operation_logs",
        sa.Column(
            "summary_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE agent_pending_actions
        SET status = 'cancelled',
            error = 'architecture_upgrade_requires_restage',
            resolved_at = now(),
            expected_versions_json = '{}'::jsonb
        WHERE status IN ('pending', 'failed')
        """
    )
    op.execute(
        """
        UPDATE agent_operation_logs
        SET before_state_json = '{}'::jsonb,
            after_state_json = '{}'::jsonb,
            event_ids_json = '[]'::jsonb,
            summary_json = jsonb_build_object(
                'legacy_snapshot_redacted', true,
                'undo_available', false
            )
        WHERE before_state_json <> '{}'::jsonb
           OR after_state_json <> '{}'::jsonb
        """
    )

    # Legacy reversal rows predate reversal_of_id. Recover the append-only
    # relationship from the original row's reversed_by_id pointer.
    op.execute(
        """
        UPDATE transactions AS reversal
        SET reversal_of_id = original.id,
            metadata_json = COALESCE(reversal.metadata_json, '{}'::jsonb)
                || jsonb_build_object('legacy_reversal_cutover', '0012')
        FROM transactions AS original
        WHERE original.reversed_by_id = reversal.id
          AND reversal.reversal_of_id IS NULL
        """
    )

    # Ensure every currency affected by a replayable cash event has a
    # family-local cash instrument. IDs are deterministic, making retries and
    # partially restored test databases safe.
    op.execute(
        """
        WITH required_cash AS (
            SELECT DISTINCT family_id, upper(currency) AS currency
            FROM transactions
            WHERE transaction_type IN (
                'buy', 'sell', 'dividend', 'interest', 'fee', 'tax'
            )
            UNION
            SELECT DISTINCT family_id, upper(fee_currency) AS currency
            FROM transactions
            WHERE fee <> 0
              AND transaction_type IN ('buy', 'sell', 'fx_exchange')
        )
        INSERT INTO instruments (
            id,
            created_at,
            updated_at,
            symbol,
            name,
            asset_class,
            currency,
            country,
            market,
            exposure_group_id,
            price_source_type,
            external_ids,
            family_id
        )
        SELECT
            md5(
                required_cash.family_id::text
                || '-0012-cash-'
                || required_cash.currency
            )::uuid,
            now(),
            now(),
            required_cash.currency,
            required_cash.currency || ' Cash',
            'cash',
            required_cash.currency,
            NULL,
            'OTHER',
            NULL,
            'fx_derived',
            jsonb_build_object('migration_revision', '0012'),
            required_cash.family_id
        FROM required_cash
        WHERE NOT EXISTS (
            SELECT 1
            FROM instruments
            WHERE instruments.family_id = required_cash.family_id
              AND instruments.asset_class = 'cash'
              AND upper(instruments.currency) = required_cash.currency
              AND upper(instruments.symbol) = required_cash.currency
        )
        """
    )

    # One row represents one call to the holding projection writer. Keeping
    # repeated effects (for example sale proceeds and a same-currency fee)
    # preserves projection_version as well as quantity.
    op.execute(
        """
        CREATE TEMP TABLE migration_0012_contributions
        ON COMMIT DROP
        AS
        SELECT
            transaction.family_id,
            transaction.account_id,
            transaction.instrument_id,
            transaction.id AS transaction_id,
            transaction.quantity::numeric(24, 6) AS delta,
            transaction.created_at,
            transaction.source
        FROM transactions AS transaction
        WHERE transaction.instrument_id IS NOT NULL
          AND transaction.transaction_type IN (
              'buy',
              'sell',
              'transfer_in',
              'transfer_out',
              'deposit',
              'withdraw',
              'fx_exchange',
              'manual_adjustment',
              'opening_balance',
              'reconciliation',
              'split',
              'reverse_split',
              'merger',
              'stock_dividend'
          )

        UNION ALL

        SELECT
            transaction.family_id,
            transaction.account_id,
            cash.id,
            transaction.id,
            transaction.amount::numeric(24, 6),
            transaction.created_at,
            transaction.source
        FROM transactions AS transaction
        JOIN LATERAL (
            SELECT instrument.id
            FROM instruments AS instrument
            WHERE instrument.family_id = transaction.family_id
              AND instrument.asset_class = 'cash'
              AND upper(instrument.currency) = upper(transaction.currency)
              AND upper(instrument.symbol) = upper(transaction.currency)
            ORDER BY instrument.id
            LIMIT 1
        ) AS cash ON true
        WHERE transaction.transaction_type IN ('buy', 'sell')

        UNION ALL

        SELECT
            transaction.family_id,
            transaction.account_id,
            cash.id,
            transaction.id,
            (-transaction.fee)::numeric(24, 6),
            transaction.created_at,
            transaction.source
        FROM transactions AS transaction
        JOIN LATERAL (
            SELECT instrument.id
            FROM instruments AS instrument
            WHERE instrument.family_id = transaction.family_id
              AND instrument.asset_class = 'cash'
              AND upper(instrument.currency) = upper(transaction.fee_currency)
              AND upper(instrument.symbol) = upper(transaction.fee_currency)
            ORDER BY instrument.id
            LIMIT 1
        ) AS cash ON true
        WHERE transaction.fee <> 0
          AND transaction.transaction_type IN ('buy', 'sell', 'fx_exchange')

        UNION ALL

        SELECT
            transaction.family_id,
            transaction.account_id,
            cash.id,
            transaction.id,
            transaction.amount::numeric(24, 6),
            transaction.created_at,
            transaction.source
        FROM transactions AS transaction
        JOIN LATERAL (
            SELECT instrument.id
            FROM instruments AS instrument
            WHERE instrument.family_id = transaction.family_id
              AND instrument.asset_class = 'cash'
              AND upper(instrument.currency) = upper(transaction.currency)
              AND upper(instrument.symbol) = upper(transaction.currency)
            ORDER BY instrument.id
            LIMIT 1
        ) AS cash ON true
        WHERE transaction.transaction_type IN (
            'dividend', 'interest', 'fee', 'tax'
        )
        """
    )
    op.execute(
        """
        CREATE INDEX migration_0012_contributions_coordinate
        ON migration_0012_contributions (
            family_id,
            account_id,
            instrument_id
        )
        """
    )

    # Replay must materialize the same zero-valued coordinates as the current
    # projection, otherwise checksum equality would depend on missing rows.
    op.execute(
        """
        INSERT INTO holdings (
            id,
            created_at,
            updated_at,
            account_id,
            instrument_id,
            quantity,
            source,
            family_id,
            projection_version,
            last_event_id
        )
        SELECT
            md5(
                coordinate.family_id::text
                || coordinate.account_id::text
                || coordinate.instrument_id::text
                || '-0012-holding'
            )::uuid,
            now(),
            now(),
            coordinate.account_id,
            coordinate.instrument_id,
            0,
            'manual',
            coordinate.family_id,
            0,
            NULL
        FROM (
            SELECT DISTINCT family_id, account_id, instrument_id
            FROM migration_0012_contributions
        ) AS coordinate
        WHERE NOT EXISTS (
            SELECT 1
            FROM holdings
            WHERE holdings.account_id = coordinate.account_id
              AND holdings.instrument_id = coordinate.instrument_id
        )
        """
    )

    # Preserve every pre-cutover holding quantity by expressing the difference
    # between it and the legacy event sum as a normal opening-balance event.
    op.execute(
        """
        CREATE TEMP TABLE migration_0012_residuals
        ON COMMIT DROP
        AS
        SELECT
            holding.id AS holding_id,
            holding.family_id,
            holding.account_id,
            holding.instrument_id,
            holding.quantity
                - COALESCE(sum(contribution.delta), 0) AS delta,
            holding.source,
            instrument.currency
        FROM holdings AS holding
        JOIN instruments AS instrument
          ON instrument.id = holding.instrument_id
         AND instrument.family_id = holding.family_id
        LEFT JOIN migration_0012_contributions AS contribution
          ON contribution.family_id = holding.family_id
         AND contribution.account_id = holding.account_id
         AND contribution.instrument_id = holding.instrument_id
        GROUP BY
            holding.id,
            holding.family_id,
            holding.account_id,
            holding.instrument_id,
            holding.quantity,
            holding.source,
            instrument.currency
        HAVING holding.quantity - COALESCE(sum(contribution.delta), 0) <> 0
        """
    )
    op.execute(
        """
        INSERT INTO transactions (
            id,
            created_at,
            updated_at,
            account_id,
            instrument_id,
            transaction_type,
            quantity,
            price,
            currency,
            amount,
            fee,
            fee_currency,
            trade_date,
            executed_at,
            settlement_date,
            external_ref,
            linked_transaction_id,
            note,
            source,
            is_reversed,
            reversed_by_id,
            family_id,
            event_version,
            idempotency_key,
            correlation_id,
            causation_id,
            created_by_user_id,
            metadata_json,
            reversal_of_id
        )
        SELECT
            md5(residual.holding_id::text || '-0012-opening')::uuid,
            now(),
            now(),
            residual.account_id,
            residual.instrument_id,
            'opening_balance',
            residual.delta,
            NULL,
            upper(residual.currency),
            0,
            0,
            upper(residual.currency),
            current_date,
            now(),
            NULL,
            'migration:0012:holding:' || residual.holding_id::text,
            NULL,
            'Legacy holding cutover opening balance',
            residual.source,
            false,
            NULL,
            residual.family_id,
            1,
            'migration:opening:' || residual.holding_id::text,
            md5(residual.holding_id::text || '-0012-opening')::uuid,
            NULL,
            NULL,
            jsonb_build_object(
                'migration_revision', '0012',
                'kind', 'legacy_holding_cutover',
                'holding_id', residual.holding_id::text
            ),
            NULL
        FROM migration_0012_residuals AS residual
        """
    )
    op.execute(
        """
        INSERT INTO migration_0012_contributions (
            family_id,
            account_id,
            instrument_id,
            transaction_id,
            delta,
            created_at,
            source
        )
        SELECT
            residual.family_id,
            residual.account_id,
            residual.instrument_id,
            md5(residual.holding_id::text || '-0012-opening')::uuid,
            residual.delta,
            now(),
            residual.source
        FROM migration_0012_residuals AS residual
        """
    )

    # Record a deterministic projection cursor for the complete replay stream.
    op.execute(
        """
        UPDATE holdings
        SET projection_version = 0,
            last_event_id = NULL
        """
    )
    op.execute(
        """
        WITH aggregate AS (
            SELECT
                family_id,
                account_id,
                instrument_id,
                count(*)::integer AS projection_version
            FROM migration_0012_contributions
            GROUP BY family_id, account_id, instrument_id
        ),
        latest AS (
            SELECT DISTINCT ON (family_id, account_id, instrument_id)
                family_id,
                account_id,
                instrument_id,
                transaction_id,
                source
            FROM migration_0012_contributions
            ORDER BY
                family_id,
                account_id,
                instrument_id,
                created_at DESC,
                transaction_id DESC
        )
        UPDATE holdings AS holding
        SET projection_version = aggregate.projection_version,
            last_event_id = latest.transaction_id,
            source = latest.source
        FROM aggregate
        JOIN latest
          ON latest.family_id = aggregate.family_id
         AND latest.account_id = aggregate.account_id
         AND latest.instrument_id = aggregate.instrument_id
        WHERE holding.family_id = aggregate.family_id
          AND holding.account_id = aggregate.account_id
          AND holding.instrument_id = aggregate.instrument_id
        """
    )

    # Add a journal envelope for every historical transaction. Existing valid
    # entries are retained; only missing entries/postings are backfilled.
    op.execute(
        """
        INSERT INTO journal_entries (
            id,
            family_id,
            transaction_id,
            event_type,
            event_version,
            correlation_id,
            occurred_at,
            description,
            created_by_user_id,
            metadata_json
        )
        SELECT
            md5(transaction.id::text || '-0012-journal')::uuid,
            transaction.family_id,
            transaction.id,
            CASE
                WHEN transaction.reversal_of_id IS NOT NULL
                    THEN 'transaction.reversed'
                ELSE 'transaction.' || transaction.transaction_type
            END,
            transaction.event_version,
            transaction.correlation_id,
            transaction.created_at,
            transaction.transaction_type || ' transaction',
            transaction.created_by_user_id,
            jsonb_build_object(
                'source', transaction.source,
                'migration_revision', '0012'
            ) || COALESCE(transaction.metadata_json, '{}'::jsonb)
        FROM transactions AS transaction
        WHERE NOT EXISTS (
            SELECT 1
            FROM journal_entries
            WHERE journal_entries.family_id = transaction.family_id
              AND journal_entries.transaction_id = transaction.id
        )
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE migration_0012_entries_to_post
        ON COMMIT DROP
        AS
        SELECT entry.id
        FROM journal_entries AS entry
        WHERE NOT EXISTS (
            SELECT 1
            FROM journal_postings AS posting
            WHERE posting.journal_entry_id = entry.id
        )
        """
    )
    op.execute(
        """
        UPDATE journal_entries AS entry
        SET metadata_json = COALESCE(entry.metadata_json, '{}'::jsonb)
            || jsonb_build_object('migration_revision', '0012')
        FROM migration_0012_entries_to_post AS pending
        WHERE entry.id = pending.id
        """
    )

    # Standard non-reversal base postings.
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(entry.id::text || '-base-debit')::uuid,
            transaction.family_id,
            entry.id,
            CASE
                WHEN transaction.transaction_type = 'buy'
                    THEN COALESCE(
                        'asset:instrument:' || transaction.instrument_id::text,
                        'asset:account:' || transaction.account_id::text
                    )
                WHEN transaction.transaction_type = 'sell'
                    THEN 'asset:cash:' || transaction.account_id::text
                        || ':' || upper(transaction.currency)
                WHEN transaction.transaction_type IN ('dividend', 'interest', 'deposit')
                    THEN 'asset:cash:' || transaction.account_id::text
                        || ':' || upper(transaction.currency)
                WHEN transaction.transaction_type IN ('fee', 'tax', 'withdraw')
                    THEN 'expense:' || transaction.transaction_type
                WHEN transaction.transaction_type = 'fx_exchange'
                     AND transaction.amount >= 0
                    THEN 'asset:cash:' || transaction.account_id::text
                        || ':' || upper(transaction.currency)
                WHEN transaction.transaction_type = 'fx_exchange'
                    THEN 'asset:fx_clearing'
                WHEN transaction.amount < 0
                    THEN 'equity:event:' || transaction.transaction_type
                ELSE COALESCE(
                    'asset:instrument:' || transaction.instrument_id::text,
                    'asset:account:' || transaction.account_id::text
                )
            END,
            transaction.account_id,
            transaction.instrument_id,
            upper(transaction.currency),
            abs(transaction.amount),
            0,
            transaction.quantity,
            '{}'::jsonb
        FROM journal_entries AS entry
        JOIN migration_0012_entries_to_post AS pending ON pending.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        WHERE transaction.reversal_of_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(entry.id::text || '-base-credit')::uuid,
            transaction.family_id,
            entry.id,
            CASE
                WHEN transaction.transaction_type = 'buy'
                    THEN 'asset:cash:' || transaction.account_id::text
                        || ':' || upper(transaction.currency)
                WHEN transaction.transaction_type = 'sell'
                    THEN COALESCE(
                        'asset:instrument:' || transaction.instrument_id::text,
                        'asset:account:' || transaction.account_id::text
                    )
                WHEN transaction.transaction_type IN ('dividend', 'interest')
                    THEN 'income:' || transaction.transaction_type
                WHEN transaction.transaction_type IN ('fee', 'tax', 'withdraw')
                    THEN 'asset:cash:' || transaction.account_id::text
                        || ':' || upper(transaction.currency)
                WHEN transaction.transaction_type = 'deposit'
                    THEN 'equity:contribution'
                WHEN transaction.transaction_type = 'fx_exchange'
                     AND transaction.amount >= 0
                    THEN 'asset:fx_clearing'
                WHEN transaction.transaction_type = 'fx_exchange'
                    THEN 'asset:cash:' || transaction.account_id::text
                        || ':' || upper(transaction.currency)
                ELSE 'equity:event:' || transaction.transaction_type
            END,
            transaction.account_id,
            transaction.instrument_id,
            upper(transaction.currency),
            0,
            abs(transaction.amount),
            -transaction.quantity,
            '{}'::jsonb
        FROM journal_entries AS entry
        JOIN migration_0012_entries_to_post AS pending ON pending.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        WHERE transaction.reversal_of_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(entry.id::text || '-fee-debit')::uuid,
            transaction.family_id,
            entry.id,
            'expense:fee',
            transaction.account_id,
            transaction.instrument_id,
            upper(transaction.fee_currency),
            abs(transaction.fee),
            0,
            NULL,
            '{}'::jsonb
        FROM journal_entries AS entry
        JOIN migration_0012_entries_to_post AS pending ON pending.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        WHERE transaction.reversal_of_id IS NULL
          AND transaction.fee <> 0
        """
    )
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(entry.id::text || '-fee-credit')::uuid,
            transaction.family_id,
            entry.id,
            'asset:cash:' || transaction.account_id::text
                || ':' || upper(transaction.fee_currency),
            transaction.account_id,
            NULL,
            upper(transaction.fee_currency),
            0,
            abs(transaction.fee),
            NULL,
            '{}'::jsonb
        FROM journal_entries AS entry
        JOIN migration_0012_entries_to_post AS pending ON pending.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        WHERE transaction.reversal_of_id IS NULL
          AND transaction.fee <> 0
        """
    )

    # Reversal journals mirror the original postings. Any malformed legacy
    # reversal whose original cannot be found gets a balanced fallback pair.
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(reversal_entry.id::text || original_posting.id::text)::uuid,
            reversal.family_id,
            reversal_entry.id,
            original_posting.account_code,
            original_posting.account_id,
            original_posting.instrument_id,
            original_posting.currency,
            original_posting.credit,
            original_posting.debit,
            -original_posting.quantity,
            original_posting.metadata_json
        FROM journal_entries AS reversal_entry
        JOIN migration_0012_entries_to_post AS pending
          ON pending.id = reversal_entry.id
        JOIN transactions AS reversal
          ON reversal.id = reversal_entry.transaction_id
        JOIN journal_entries AS original_entry
          ON original_entry.transaction_id = reversal.reversal_of_id
         AND original_entry.family_id = reversal.family_id
        JOIN journal_postings AS original_posting
          ON original_posting.journal_entry_id = original_entry.id
        WHERE reversal.reversal_of_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE migration_0012_reversal_fallback
        ON COMMIT DROP
        AS
        SELECT entry.id
        FROM journal_entries AS entry
        JOIN migration_0012_entries_to_post AS pending ON pending.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        WHERE transaction.reversal_of_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM journal_postings AS posting
              WHERE posting.journal_entry_id = entry.id
          )
        """
    )
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(entry.id::text || '-fallback-debit')::uuid,
            transaction.family_id,
            entry.id,
            'equity:migration-reversal',
            transaction.account_id,
            transaction.instrument_id,
            upper(transaction.currency),
            abs(transaction.amount),
            0,
            transaction.quantity,
            '{}'::jsonb
        FROM journal_entries AS entry
        JOIN migration_0012_reversal_fallback AS fallback ON fallback.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        """
    )
    op.execute(
        """
        INSERT INTO journal_postings (
            id,
            family_id,
            journal_entry_id,
            account_code,
            account_id,
            instrument_id,
            currency,
            debit,
            credit,
            quantity,
            metadata_json
        )
        SELECT
            md5(entry.id::text || '-fallback-credit')::uuid,
            transaction.family_id,
            entry.id,
            'equity:migration-reversal-contra',
            transaction.account_id,
            transaction.instrument_id,
            upper(transaction.currency),
            0,
            abs(transaction.amount),
            -transaction.quantity,
            '{}'::jsonb
        FROM journal_entries AS entry
        JOIN migration_0012_reversal_fallback AS fallback ON fallback.id = entry.id
        JOIN transactions AS transaction ON transaction.id = entry.transaction_id
        """
    )

    op.execute(
        """
        INSERT INTO audit_events (
            id,
            family_id,
            occurred_at,
            actor_user_id,
            action,
            aggregate_type,
            aggregate_id,
            correlation_id,
            causation_id,
            summary_json
        )
        SELECT
            md5(transaction.id::text || '-0012-audit')::uuid,
            transaction.family_id,
            transaction.created_at,
            transaction.created_by_user_id,
            CASE
                WHEN transaction.reversal_of_id IS NOT NULL
                    THEN 'transaction.reversed'
                ELSE 'transaction.' || transaction.transaction_type
            END,
            'transaction',
            transaction.id,
            transaction.correlation_id,
            transaction.causation_id,
            jsonb_build_object(
                'migration_revision', '0012',
                'account_id', transaction.account_id::text,
                'instrument_id', transaction.instrument_id::text,
                'transaction_type', transaction.transaction_type,
                'currency', transaction.currency,
                'event_version', transaction.event_version
            )
        FROM transactions AS transaction
        WHERE NOT EXISTS (
            SELECT 1
            FROM audit_events AS audit
            WHERE audit.family_id = transaction.family_id
              AND audit.aggregate_type = 'transaction'
              AND audit.aggregate_id = transaction.id
        )
        """
    )
    op.execute(
        """
        INSERT INTO outbox_events (
            id,
            family_id,
            occurred_at,
            aggregate_type,
            aggregate_id,
            event_type,
            event_version,
            idempotency_key,
            correlation_id,
            causation_id,
            payload_json,
            published_at,
            attempt_count,
            last_error
        )
        SELECT
            md5(transaction.id::text || '-0012-outbox')::uuid,
            transaction.family_id,
            transaction.created_at,
            'transaction',
            transaction.id,
            CASE
                WHEN transaction.reversal_of_id IS NOT NULL
                    THEN 'transaction.reversed'
                ELSE 'transaction.' || transaction.transaction_type
            END,
            transaction.event_version,
            transaction.idempotency_key,
            transaction.correlation_id,
            transaction.causation_id,
            jsonb_build_object(
                'migration_revision', '0012',
                'transaction_id', transaction.id::text,
                'family_id', transaction.family_id::text,
                'account_id', transaction.account_id::text,
                'instrument_id', transaction.instrument_id::text,
                'transaction_type', transaction.transaction_type,
                'quantity', transaction.quantity::text,
                'amount', transaction.amount::text,
                'currency', transaction.currency,
                'reversal_of_id', transaction.reversal_of_id::text
            ),
            NULL,
            0,
            NULL
        FROM transactions AS transaction
        WHERE NOT EXISTS (
            SELECT 1
            FROM outbox_events AS outbox
            WHERE outbox.family_id = transaction.family_id
              AND (
                  outbox.idempotency_key = transaction.idempotency_key
                  OR (
                      outbox.aggregate_type = 'transaction'
                      AND outbox.aggregate_id = transaction.id
                  )
              )
        )
        """
    )


def downgrade() -> None:
    # Reset materialized cursors before removing migration-created events.
    op.execute(
        """
        UPDATE holdings
        SET projection_version = 0,
            last_event_id = NULL
        """
    )
    op.execute(
        """
        DELETE FROM outbox_events
        WHERE payload_json ->> 'migration_revision' = '0012'
        """
    )
    op.execute(
        """
        DELETE FROM audit_events
        WHERE summary_json ->> 'migration_revision' = '0012'
        """
    )
    op.execute(
        """
        DELETE FROM journal_entries
        WHERE metadata_json ->> 'migration_revision' = '0012'
        """
    )
    op.execute(
        """
        DELETE FROM transactions
        WHERE metadata_json ->> 'migration_revision' = '0012'
          AND metadata_json ->> 'kind' = 'legacy_holding_cutover'
        """
    )
    op.execute(
        """
        UPDATE transactions
        SET reversal_of_id = NULL,
            metadata_json = metadata_json - 'legacy_reversal_cutover'
        WHERE metadata_json ->> 'legacy_reversal_cutover' = '0012'
        """
    )

    op.drop_column("agent_operation_logs", "summary_json")
    op.drop_column("agent_operation_logs", "event_ids_json")
    op.drop_column("agent_pending_actions", "expected_versions_json")
