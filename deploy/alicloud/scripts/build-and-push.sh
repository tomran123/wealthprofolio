#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: build-and-push.sh backend|frontend|all

Required environment:
  ACR_PUSH_REGISTRY     Public ACR endpoint used by the local Docker client
  ACR_RUNTIME_REGISTRY  VPC ACR endpoint used by SAE/Function Compute
  ACR_NAMESPACE         Existing ACR namespace
  IMAGE_TAG             Immutable release tag (Git SHA is recommended)

Frontend additionally requires:
  BACKEND_INTERNAL_URL  Private API URL reachable from the SAE frontend

Backend optional:
  PYTHON_PACKAGE_INDEX_URL
                        Trusted HTTPS Python package index. Defaults to the
                        official PyPI index declared by backend/Dockerfile.

The script never logs in to ACR and never accepts AccessKeys. Run the official
`docker login` command from the ACR console before invoking this script.
EOF
}

component="${1:-}"
if [[ "${component}" != "backend" && "${component}" != "frontend" && "${component}" != "all" ]]; then
  usage >&2
  exit 64
fi

: "${ACR_PUSH_REGISTRY:?Set ACR_PUSH_REGISTRY}"
: "${ACR_RUNTIME_REGISTRY:?Set ACR_RUNTIME_REGISTRY}"
: "${ACR_NAMESPACE:?Set ACR_NAMESPACE}"
: "${IMAGE_TAG:?Set an immutable IMAGE_TAG}"

if [[ ! "${IMAGE_TAG}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{6,127}$ ]]; then
  echo "IMAGE_TAG must be an immutable, registry-safe tag of at least 7 characters" >&2
  exit 64
fi

platform="${TARGET_PLATFORM:-linux/amd64}"
backend_push_image="${ACR_PUSH_REGISTRY}/${ACR_NAMESPACE}/wealthprofolio-backend:${IMAGE_TAG}"
backend_runtime_image="${ACR_RUNTIME_REGISTRY}/${ACR_NAMESPACE}/wealthprofolio-backend:${IMAGE_TAG}"
frontend_push_image="${ACR_PUSH_REGISTRY}/${ACR_NAMESPACE}/wealthprofolio-frontend:${IMAGE_TAG}"
frontend_runtime_image="${ACR_RUNTIME_REGISTRY}/${ACR_NAMESPACE}/wealthprofolio-frontend:${IMAGE_TAG}"

build_backend() {
  python_package_index_url="${PYTHON_PACKAGE_INDEX_URL:-https://pypi.org/simple}"
  if [[ ! "${python_package_index_url}" =~ ^https://[^[:space:]]+$ ]]; then
    echo "PYTHON_PACKAGE_INDEX_URL must be an HTTPS URL" >&2
    exit 64
  fi
  if [[ "${python_package_index_url}" =~ ^https://[^/]*@ ]]; then
    echo "PYTHON_PACKAGE_INDEX_URL must not embed credentials" >&2
    exit 64
  fi

  docker buildx build \
    --platform "${platform}" \
    --pull \
    --provenance=true \
    --sbom=true \
    --target runtime \
    --build-arg "PYTHON_PACKAGE_INDEX_URL=${python_package_index_url}" \
    --tag "${backend_push_image}" \
    --push \
    backend
  printf 'backend_image_url = "%s"\n' "${backend_runtime_image}"
}

build_frontend() {
  : "${BACKEND_INTERNAL_URL:?Set BACKEND_INTERNAL_URL before building the frontend}"
  if [[ ! "${BACKEND_INTERNAL_URL}" =~ ^https?:// ]]; then
    echo "BACKEND_INTERNAL_URL must start with http:// or https://" >&2
    exit 64
  fi
  docker buildx build \
    --platform "${platform}" \
    --pull \
    --provenance=true \
    --sbom=true \
    --target runtime \
    --build-arg "BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL}" \
    --tag "${frontend_push_image}" \
    --push \
    frontend
  printf 'frontend_image_url = "%s"\n' "${frontend_runtime_image}"
}

case "${component}" in
  backend)
    build_backend
    ;;
  frontend)
    build_frontend
    ;;
  all)
    build_backend
    build_frontend
    ;;
esac
