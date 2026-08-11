\set ON_ERROR_STOP on

-- This script is read-only. Run it while connected with the runtime
-- DATABASE_URL; current_user must be the actual API/worker login role.
DO $verify$
DECLARE
  append_only_table text;
  mutable_table text;
  application_sequence text;
BEGIN
  IF has_schema_privilege(current_user, 'public', 'CREATE') THEN
    RAISE EXCEPTION 'runtime_must_not_create_schema_objects';
  END IF;

  FOREACH append_only_table IN ARRAY ARRAY[
    'public.transactions',
    'public.journal_entries',
    'public.journal_postings',
    'public.audit_events',
    'public.outbox_events',
    'public.price_snapshots',
    'public.fx_rate_snapshots',
    'public.valuation_snapshots'
  ]
  LOOP
    IF NOT has_table_privilege(current_user, append_only_table, 'SELECT')
       OR NOT has_table_privilege(current_user, append_only_table, 'INSERT') THEN
      RAISE EXCEPTION 'runtime_missing_append_privilege:%', append_only_table;
    END IF;
    IF has_table_privilege(current_user, append_only_table, 'UPDATE')
       OR has_table_privilege(current_user, append_only_table, 'DELETE')
       OR has_table_privilege(current_user, append_only_table, 'TRUNCATE') THEN
      RAISE EXCEPTION 'runtime_has_mutation_privilege:%', append_only_table;
    END IF;
  END LOOP;

  -- Every remaining application table is ordinary mutable state. This dynamic
  -- check catches new Sprint tables and future migrations that a static allow
  -- list could silently omit.
  FOR mutable_table IN
    SELECT format('%I.%I', namespace.nspname, relation.relname)
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
      AND relation.relname NOT IN (
        'alembic_version',
        'audit_events',
        'fx_rate_snapshots',
        'holdings',
        'journal_entries',
        'journal_postings',
        'outbox_events',
        'price_snapshots',
        'transaction_metadata_projections',
        'transactions',
        'valuation_snapshots'
      )
    ORDER BY relation.relname
  LOOP
    IF NOT has_table_privilege(current_user, mutable_table, 'SELECT')
       OR NOT has_table_privilege(current_user, mutable_table, 'INSERT')
       OR NOT has_table_privilege(current_user, mutable_table, 'UPDATE')
       OR NOT has_table_privilege(current_user, mutable_table, 'DELETE') THEN
      RAISE EXCEPTION 'runtime_missing_mutable_table_privilege:%', mutable_table;
    END IF;
    IF has_table_privilege(current_user, mutable_table, 'TRUNCATE') THEN
      RAISE EXCEPTION 'runtime_can_truncate_mutable_table:%', mutable_table;
    END IF;
  END LOOP;

  IF NOT has_table_privilege(current_user, 'public.holdings', 'SELECT')
     OR NOT has_table_privilege(current_user, 'public.holdings', 'INSERT') THEN
    RAISE EXCEPTION 'runtime_missing_holdings_projection_privilege';
  END IF;
  IF has_table_privilege(current_user, 'public.holdings', 'UPDATE')
     OR has_table_privilege(current_user, 'public.holdings', 'DELETE')
     OR has_table_privilege(current_user, 'public.holdings', 'TRUNCATE') THEN
    RAISE EXCEPTION 'runtime_has_broad_holdings_mutation_privilege';
  END IF;
  IF NOT has_column_privilege(
    current_user,
    'public.holdings',
    'projection_version',
    'UPDATE'
  ) OR has_column_privilege(
    current_user,
    'public.holdings',
    'family_id',
    'UPDATE'
  ) THEN
    RAISE EXCEPTION 'runtime_holdings_column_privileges_are_wrong';
  END IF;

  IF NOT has_table_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'SELECT'
  ) OR NOT has_table_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'INSERT'
  ) THEN
    RAISE EXCEPTION 'runtime_missing_transaction_metadata_projection_privilege';
  END IF;
  IF has_table_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'UPDATE'
  ) OR has_table_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'DELETE'
  ) OR has_table_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'TRUNCATE'
  ) THEN
    RAISE EXCEPTION 'runtime_has_broad_transaction_metadata_mutation_privilege';
  END IF;
  IF NOT has_column_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'version',
    'UPDATE'
  ) OR has_column_privilege(
    current_user,
    'public.transaction_metadata_projections',
    'family_id',
    'UPDATE'
  ) THEN
    RAISE EXCEPTION 'runtime_transaction_metadata_column_privileges_are_wrong';
  END IF;

  IF has_table_privilege(current_user, 'public.alembic_version', 'UPDATE')
     OR has_table_privilege(current_user, 'public.alembic_version', 'INSERT')
     OR has_table_privilege(current_user, 'public.alembic_version', 'DELETE')
     OR has_table_privilege(current_user, 'public.alembic_version', 'TRUNCATE')
     OR NOT has_table_privilege(
       current_user,
       'public.alembic_version',
       'SELECT'
     ) THEN
    RAISE EXCEPTION 'runtime_can_forge_alembic_state';
  END IF;

  FOR application_sequence IN
    SELECT format('%I.%I', namespace.nspname, relation.relname)
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind = 'S'
    ORDER BY relation.relname
  LOOP
    IF NOT has_sequence_privilege(
      current_user,
      application_sequence,
      'USAGE'
    ) OR NOT has_sequence_privilege(
      current_user,
      application_sequence,
      'SELECT'
    ) THEN
      RAISE EXCEPTION 'runtime_missing_sequence_privilege:%', application_sequence;
    END IF;
  END LOOP;

  IF NOT has_function_privilege(
    current_user,
    'public.wp_mark_transaction_reversed(uuid,uuid,uuid)',
    'EXECUTE'
  ) OR NOT has_function_privilege(
    current_user,
    'public.wp_delete_draft_transaction(uuid,uuid)',
    'EXECUTE'
  ) OR NOT has_function_privilege(
    current_user,
    'public.wp_record_outbox_delivery(uuid,uuid,timestamp with time zone,text)',
    'EXECUTE'
  ) THEN
    RAISE EXCEPTION 'runtime_missing_guarded_function_execute';
  END IF;
END;
$verify$;

SELECT
  current_database() AS database_name,
  current_user AS verified_runtime_role,
  'PASS' AS least_privilege_contract;
