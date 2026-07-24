"""Authenticated API smoke test. Run against an empty migrated test database."""

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        login = client.post("/api/auth/login", json={"username": "admin", "password": "change-me"})
        assert login.status_code == 200, login.text
        assert login.cookies.get("wp_session")

        checks = (
            "/api/portfolio/summary",
            "/api/portfolio/snapshots?limit=10",
            "/api/transactions?limit=10",
            "/api/agent/sessions",
            "/api/agent/logs?limit=10",
            "/api/settings/llm-providers",
        )
        for path in checks:
            response = client.get(path)
            assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        assert client.post("/api/auth/logout").status_code == 200
        print(f"api_smoke_ok endpoints={len(checks) + 3}")


if __name__ == "__main__":
    main()
