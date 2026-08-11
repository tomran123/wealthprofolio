FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
ARG PYTHON_PACKAGE_INDEX_URL=https://pypi.org/simple
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install \
        --timeout 120 \
        --retries 8 \
        --index-url "${PYTHON_PACKAGE_INDEX_URL}" \
        --require-hashes \
        -r requirements.lock

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        postgresql-client \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /app/data/documents \
    && chown -R app:app /app /home/app

COPY --from=builder /opt/venv /opt/venv

COPY --chown=app:app . .

EXPOSE 8000

USER app

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl --fail --silent http://127.0.0.1:8000/api/health || exit 1

# Database migrations are deliberately not run here.  Compose uses the
# one-shot "migrate" service and production uses an SAE Job.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
