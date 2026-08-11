\set ON_ERROR_STOP on

-- Run as wp_migration_owner after Alembic reaches head and before enabling any
-- API/worker replicas. The role name is configurable but never accepts a
-- password here.
\if :{?runtime_role}
\else
  \set runtime_role wp_runtime
\endif

SELECT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'runtime_role'
) AS runtime_role_exists \gset
\if :runtime_role_exists
\else
  \echo 'Missing runtime role. Create/bootstrap it before hardening.'
  \quit 3
\endif

BEGIN;

REVOKE CREATE ON SCHEMA public FROM :"runtime_role";
GRANT USAGE ON SCHEMA public TO :"runtime_role";

-- Connected as the migration owner, these defaults apply to objects created
-- by later Alembic revisions. Each release still reruns this hardening script
-- before runtime replicas are enabled.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"runtime_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Backfill the default privilege baseline onto every object that already
-- exists. Initial setup runs bootstrap before Alembic, so defaults cover new
-- objects; this explicit grant also makes the script safe to rerun after an
-- older deployment or a migration created by a different owner.
GRANT SELECT, INSERT, UPDATE, DELETE
  ON ALL TABLES IN SCHEMA public TO :"runtime_role";
GRANT USAGE, SELECT
  ON ALL SEQUENCES IN SCHEMA public TO :"runtime_role";

-- Remove any column-level UPDATE grants left by an earlier compatibility
-- release before rebuilding the exact privilege set below.
SELECT format(
  'REVOKE UPDATE (%s) ON TABLE %I.%I FROM %I',
  string_agg(format('%I', column_name), ', ' ORDER BY ordinal_position),
  table_schema,
  table_name,
  :'runtime_role'
)
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'transactions',
    'journal_entries',
    'journal_postings',
    'audit_events',
    'outbox_events',
    'holdings',
    'transaction_metadata_projections',
    'price_snapshots',
    'fx_rate_snapshots',
    'valuation_snapshots'
  )
GROUP BY table_schema, table_name
ORDER BY table_name
\gexec

REVOKE ALL PRIVILEGES ON TABLE
  public.transactions,
  public.journal_entries,
  public.journal_postings,
  public.audit_events,
  public.outbox_events,
  public.holdings,
  public.transaction_metadata_projections,
  public.price_snapshots,
  public.fx_rate_snapshots,
  public.valuation_snapshots,
  public.alembic_version
FROM :"runtime_role";

-- Immutable business/event rows are append-only to runtime.
GRANT SELECT, INSERT ON TABLE
  public.transactions,
  public.journal_entries,
  public.journal_postings,
  public.audit_events,
  public.outbox_events,
  public.price_snapshots,
  public.fx_rate_snapshots,
  public.valuation_snapshots
TO :"runtime_role";

-- Runtime may read Alembic state but cannot forge a migration revision.
GRANT SELECT ON TABLE public.alembic_version TO :"runtime_role";

-- Holdings and transaction metadata are materialized projections. Runtime can
-- insert coordinates and update only projection-owned fields.
GRANT SELECT, INSERT ON TABLE public.holdings TO :"runtime_role";
GRANT UPDATE (
  updated_at,
  quantity,
  source,
  projection_version,
  last_event_id
) ON TABLE public.holdings TO :"runtime_role";

GRANT SELECT, INSERT ON TABLE public.transaction_metadata_projections
TO :"runtime_role";
GRANT UPDATE (
  updated_at,
  trade_date,
  executed_at,
  settlement_date,
  external_ref,
  note,
  version,
  last_event_id
) ON TABLE public.transaction_metadata_projections TO :"runtime_role";

-- Revision 0015 is the single source of truth for these SECURITY DEFINER
-- bodies and their trigger-compatible semantics. Hardening must only grant
-- execution; CREATE OR REPLACE here could silently overwrite a newer contract.
REVOKE ALL ON FUNCTION
  public.wp_mark_transaction_reversed(uuid, uuid, uuid),
  public.wp_delete_draft_transaction(uuid, uuid),
  public.wp_record_outbox_delivery(uuid, uuid, timestamptz, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  public.wp_mark_transaction_reversed(uuid, uuid, uuid),
  public.wp_delete_draft_transaction(uuid, uuid),
  public.wp_record_outbox_delivery(uuid, uuid, timestamptz, text)
TO :"runtime_role";

COMMIT;

\echo 'Runtime privilege hardening complete.'
\echo 'Run verify-runtime-privileges.sql while connected as the runtime role.'
