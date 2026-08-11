#!/usr/bin/env bash
set -euo pipefail

for command_name in aliyun jq; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "${command_name} is required" >&2
    exit 69
  fi
done

: "${ALICLOUD_REGION:?Set ALICLOUD_REGION}"
: "${SAE_NAMESPACE_ID:?Set SAE_NAMESPACE_ID}"
: "${VPC_ID:?Set VPC_ID}"
: "${VSWITCH_ID:?Set VSWITCH_ID}"
: "${SECURITY_GROUP_ID:?Set SECURITY_GROUP_ID}"
: "${BACKEND_IMAGE_URL:?Set immutable BACKEND_IMAGE_URL}"
: "${SAE_MIGRATION_SECRET_NAME:?Set SAE_MIGRATION_SECRET_NAME}"
: "${SAE_MIGRATION_SECRET_ID:?Set numeric SAE_MIGRATION_SECRET_ID}"
: "${RELEASE_ID:?Set immutable RELEASE_ID}"

if [[ "${CONFIRM_CREATE_JOB:-}" != "YES" ]]; then
  echo "This creates an Alibaba Cloud SAE Job template." >&2
  echo "Re-run with CONFIRM_CREATE_JOB=YES after reviewing all variables." >&2
  exit 65
fi

if [[ ! "${SAE_MIGRATION_SECRET_ID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "SAE_MIGRATION_SECRET_ID must be a positive integer" >&2
  exit 64
fi

safe_release="$(printf '%s' "${RELEASE_ID}" | tr -cd '[:alnum:]-' | cut -c1-18)"
if [[ -z "${safe_release}" ]]; then
  echo "RELEASE_ID has no characters usable in an SAE Job name" >&2
  exit 64
fi
job_name="wp-migrate-${safe_release}"

envs="$(
  jq -cn \
    --arg secret_name "${SAE_MIGRATION_SECRET_NAME}" \
    --argjson secret_id "${SAE_MIGRATION_SECRET_ID}" \
    '[
      {
        name: ("sae-sys-secret-all-" + $secret_name),
        valueFrom: {
          secretRef: {
            secretId: $secret_id,
            key: ""
          }
        }
      }
    ]'
)"

response="$(
  aliyun sae CreateJob \
    --region "${ALICLOUD_REGION}" \
    --AppName "${job_name}" \
    --AppDescription "One-shot Alembic migration ${RELEASE_ID}" \
    --NamespaceId "${SAE_NAMESPACE_ID}" \
    --VpcId "${VPC_ID}" \
    --VSwitchId "${VSWITCH_ID}" \
    --SecurityGroupId "${SECURITY_GROUP_ID}" \
    --AutoConfig false \
    --PackageType Image \
    --ImageUrl "${BACKEND_IMAGE_URL}" \
    --Cpu 500 \
    --Memory 1024 \
    --Replicas 1 \
    --Command alembic \
    --CommandArgs '["upgrade","head"]' \
    --Envs "${envs}" \
    --Timezone Asia/Shanghai \
    --Workload job \
    --ConcurrencyPolicy Forbid \
    --Timeout 900 \
    --BackoffLimit 0 \
    --ProgrammingLanguage python
)"

printf '%s\n' "${response}" | jq .
job_template_id="$(printf '%s\n' "${response}" | jq -er '.Data.AppId')"

echo
echo "Migration Job template created."
printf 'SAE_MIGRATION_JOB_ID=%q\n' "${job_template_id}"
echo "The schema has NOT been changed yet. Review the template in SAE, then use run-migration-job.sh."
