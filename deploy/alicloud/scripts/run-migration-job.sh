#!/usr/bin/env bash
set -euo pipefail

for command_name in aliyun jq; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "${command_name} is required" >&2
    exit 69
  fi
done

: "${ALICLOUD_REGION:?Set ALICLOUD_REGION}"
: "${SAE_MIGRATION_JOB_ID:?Set SAE_MIGRATION_JOB_ID}"
: "${RELEASE_ID:?Set immutable RELEASE_ID}"

if [[ "${CONFIRM_RUN_MIGRATION:-}" != "YES" ]]; then
  echo "This executes 'alembic upgrade head' against the configured production database." >&2
  echo "Confirm that the RDS backup is complete, then re-run with CONFIRM_RUN_MIGRATION=YES." >&2
  exit 65
fi

event_id="$(printf 'migration-%s' "${RELEASE_ID}" | tr -cd '[:alnum:]._-' | cut -c1-64)"
response="$(
  aliyun sae ExecJob \
    --region "${ALICLOUD_REGION}" \
    --AppId "${SAE_MIGRATION_JOB_ID}" \
    --EventId "${event_id}" \
    --Replicas 1
)"

printf '%s\n' "${response}" | jq .
execution_id="$(printf '%s\n' "${response}" | jq -er '.Data.Data')"

echo
printf 'Migration execution submitted: %s\n' "${execution_id}"
echo "Do not enable SAE API/worker replicas until the SAE Job record is Succeeded"
echo "and its logs show Alembic at head. The EventId makes a repeated request idempotent."
