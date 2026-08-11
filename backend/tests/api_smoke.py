"""Authenticated API smoke test for the dedicated disposable database."""

# The disposable-target guard intentionally runs before importing application
# modules, because those modules construct the database engine at import time.
# ruff: noqa: E402

import os
from urllib.parse import unquote, urlsplit

from fastapi.testclient import TestClient

ORIGIN = "http://localhost:3000"


def _require_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        parsed = urlsplit(database_url)
        database_name = unquote(parsed.path.lstrip("/"))
        target = (
            parsed.scheme,
            parsed.hostname,
            parsed.port,
            database_name,
            parsed.query,
            parsed.fragment,
        )
    except ValueError as exc:
        raise RuntimeError("refusing_invalid_database_url") from exc
    if target != (
        "postgresql+asyncpg",
        "127.0.0.1",
        64236,
        "codex_legacy_smoke_20260728",
        "",
        "",
    ):
        raise RuntimeError(
            "refusing_non_disposable_database:"
            "expected_127.0.0.1_64236_codex_legacy_smoke_20260728"
        )


_require_disposable_database()

from app.main import app


def main() -> None:
    _require_disposable_database()
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "change-me"},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200, login.text
        assert login.cookies.get("wp_session")
        assert login.cookies.get("wp_csrf")
        family_id = login.json()["active_family_id"]
        family_headers = {"X-Family-ID": family_id}

        checks = (
            "/api/auth/me",
            "/api/portfolio/summary",
            "/api/portfolio/snapshots?limit=10",
            "/api/transactions?limit=10",
            "/api/agent/sessions",
            "/api/agent/logs?limit=10",
            "/api/settings/llm-providers",
        )
        for path in checks:
            response = client.get(path, headers=family_headers)
            assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
            if path == "/api/auth/me":
                assert response.json()["active_family_id"] == family_id
        assert (
            client.post(
                "/api/auth/logout",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": client.cookies["wp_csrf"],
                },
            ).status_code
            == 200
        )
        print(f"api_smoke_ok endpoints={len(checks) + 3}")


if __name__ == "__main__":
    main()
