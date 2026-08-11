"""Isolated PostgreSQL/pgvector integration for the Sprint 1 document loop.

Run against a disposable database only:
    DATABASE_URL=... DOCUMENT_STORAGE_LOCAL_PATH=... \
      PYTHONPATH=. python tests/document_rag_integration.py
"""

import asyncio
import hashlib
import os
import uuid
from decimal import Decimal

import fitz
import httpx
from sqlalchemy import func, select

from app.agent.state import collect_expected_versions
from app.core.db import AsyncSessionLocal
from app.core.family_scope import RequestContext, bind_request_context
from app.core.security import hash_password
from app.main import app
from app.models import (
    Account,
    AuditEvent,
    DocumentLink,
    Family,
    FamilyMembership,
    Holding,
    Institution,
    Instrument,
    JournalEntry,
    Owner,
    Transaction,
    User,
)
from app.models.enums import (
    AccountType,
    AssetClass,
    InstitutionType,
    MarketRegion,
    OwnerType,
    PriceSourceType,
    TransactionSource,
    TransactionType,
)
from app.schemas.transaction import CashTransactionCreate
from app.services import transaction_service
from app.services.auth_service import ensure_initial_user

ORIGIN = "http://localhost:3000"


def statement_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "2026-07-24 BUY AAPL 10 200 USD 2000")
    content = document.tobytes()
    document.close()
    return content


async def seed() -> dict:
    async with AsyncSessionLocal() as db:
        await ensure_initial_user(db, "admin", "change-me")
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        family_a = (
            await db.execute(select(Family).where(Family.slug == "default-family"))
        ).scalar_one()
        bind_request_context(
            db,
            RequestContext(
                user_id=admin.id,
                family_id=family_a.id,
                role="admin",
                token_jti=uuid.uuid4(),
            ),
        )
        owner = Owner(name="Integration Owner", owner_type=OwnerType.INDIVIDUAL)
        institution = Institution(
            name="Integration Broker",
            institution_type=InstitutionType.BROKER,
            country="US",
        )
        db.add_all([owner, institution])
        await db.flush()
        account = Account(
            owner_id=owner.id,
            institution_id=institution.id,
            name="Integration Brokerage",
            account_type=AccountType.BROKERAGE,
            base_currency="USD",
        )
        instrument = Instrument(
            symbol="AAPL",
            name="Apple Inc.",
            asset_class=AssetClass.EQUITY,
            currency="USD",
            market=MarketRegion.US,
            price_source_type=PriceSourceType.MANUAL,
        )
        db.add_all([account, instrument])
        await db.commit()
        await transaction_service.create_cash_transaction(
            db,
            CashTransactionCreate(
                account_id=account.id,
                amount=Decimal(5000),
                currency="USD",
                transaction_type=TransactionType.DEPOSIT,
                source=TransactionSource.MANUAL,
            ),
            idempotency_key="integration:seed-cash",
        )

        family_b = Family(name="Other Family", slug=f"other-{uuid.uuid4().hex[:8]}")
        user_b = User(
            username=f"other-{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("other-password"),
            display_name="Other User",
        )
        db.add_all([family_b, user_b])
        await db.flush()
        db.add(
            FamilyMembership(
                family_id=family_b.id,
                user_id=user_b.id,
                role="admin",
                is_active=True,
            )
        )
        await db.commit()
        return {
            "family_a_id": str(family_a.id),
            "account_id": str(account.id),
            "instrument_id": str(instrument.id),
            "other_username": user_b.username,
        }


async def login(client: httpx.AsyncClient, username: str, password: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text


def unsafe_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": client.cookies["wp_csrf"],
    }


async def run() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    assert "127.0.0.1:62799" in database_url, "refusing_non_disposable_database"
    seeded = await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=ORIGIN,
        follow_redirects=True,
    ) as family_a:
        await login(family_a, "admin", "change-me")
        content = statement_pdf()
        digest = hashlib.sha256(content).hexdigest()
        response = await family_a.post(
            "/api/v1/documents/upload-intents",
            json={
                "filename": "broker-statement.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(content),
                "sha256": digest,
                "document_type": "transaction_statement",
                "account_id": seeded["account_id"],
            },
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        intent = response.json()
        assert intent["upload"]["headers"]["X-Upload-Token"]

        upload_headers = {
            **unsafe_headers(family_a),
            **intent["upload"]["headers"],
        }
        response = await family_a.put(
            intent["upload"]["url"],
            content=content,
            headers=upload_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["sha256"] == digest

        response = await family_a.post(
            f"/api/v1/documents/{intent['document_id']}/complete",
            json={"upload_token": intent["upload_token"], "sha256": digest},
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 202, response.text
        completion = response.json()
        job_id = completion["job"]["id"]

        response = await family_a.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "succeeded", response.text

        response = await family_a.get(f"/api/v1/documents/{intent['document_id']}")
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["status"] == "ready"
        assert detail["page_count"] == 1
        assert detail["pages"][0]["preview_url"]
        assert detail["extractions"][0]["fields"]

        response = await family_a.get(detail["pages"][0]["preview_url"])
        assert response.status_code == 200
        assert response.headers["cache-control"].startswith("private")
        preview_url = detail["pages"][0]["preview_url"]

        response = await family_a.post(
            "/api/v1/knowledge/search",
            json={"query": "AAPL", "limit": 10},
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"], response.text
        assert response.json()["retrieval_mode"] == "hybrid", response.text

        response = await family_a.post(
            "/api/v1/knowledge/query",
            json={"question": "What AAPL trade appears in the statement?", "limit": 5},
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        assert response.json()["citations"], response.text

        # SHA-256 deduplication reuses the private object and existing job.
        response = await family_a.post(
            "/api/v1/documents/upload-intents",
            json={
                "filename": "same-content.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(content),
                "sha256": digest,
                "document_type": "transaction_statement",
                "account_id": seeded["account_id"],
            },
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        duplicate = response.json()
        assert duplicate["duplicate"] is True
        assert duplicate["document_id"] == intent["document_id"]
        assert duplicate["upload"] is None
        response = await family_a.post(
            f"/api/v1/documents/{duplicate['document_id']}/complete",
            json={"upload_token": None, "sha256": digest},
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 202, response.text

        # Clients may omit the hash when creating an intent. The server must
        # still deduplicate after inspection without exposing a unique race.
        response = await family_a.post(
            "/api/v1/documents/upload-intents",
            json={
                "filename": "same-content-no-client-hash.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(content),
                "document_type": "transaction_statement",
                "account_id": seeded["account_id"],
            },
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        hashless_intent = response.json()
        assert hashless_intent["duplicate"] is False
        response = await family_a.put(
            hashless_intent["upload"]["url"],
            content=content,
            headers={
                **unsafe_headers(family_a),
                **hashless_intent["upload"]["headers"],
            },
        )
        assert response.status_code == 200, response.text
        response = await family_a.post(
            f"/api/v1/documents/{hashless_intent['document_id']}/complete",
            json={"upload_token": hashless_intent["upload_token"]},
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 202, response.text
        assert response.json()["document"]["id"] == intent["document_id"]
        response = await family_a.get(
            f"/api/v1/documents/{hashless_intent['document_id']}"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "archived"

        response = await family_a.post(
            f"/api/v1/documents/{intent['document_id']}/transaction-drafts",
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        draft = response.json()
        assert draft["status"] == "pending_review"
        assert draft["items"][0]["account_id"] == seeded["account_id"]
        assert draft["items"][0]["instrument_id"] == seeded["instrument_id"]

        response = await family_a.post(
            (
                f"/api/v1/documents/{intent['document_id']}/transaction-drafts/"
                f"{draft['extraction_id']}/confirm"
            ),
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"

        # A second confirmation is idempotent and cannot duplicate the event.
        response = await family_a.post(
            (
                f"/api/v1/documents/{intent['document_id']}/transaction-drafts/"
                f"{draft['extraction_id']}/confirm"
            ),
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text

        # Reprocessing supersedes derived data but preserves the confirmed
        # draft as audit evidence; it must produce a fresh review draft.
        response = await family_a.post(
            f"/api/v1/documents/{intent['document_id']}/reprocess",
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 202, response.text
        assert response.json()["job"]["status"] == "queued"
        response = await family_a.get(
            f"/api/v1/jobs/{response.json()['job']['id']}"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "succeeded", response.text
        response = await family_a.post(
            f"/api/v1/documents/{intent['document_id']}/transaction-drafts",
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        replacement_draft = response.json()
        assert replacement_draft["status"] == "pending_review"
        assert replacement_draft["id"] != draft["id"]

        # Cancelling the replacement draft changes no ledger business data.
        response = await family_a.post(
            (
                f"/api/v1/documents/{intent['document_id']}/transaction-drafts/"
                f"{replacement_draft['extraction_id']}/cancel"
            ),
            headers=unsafe_headers(family_a),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"

    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as family_b:
        await login(family_b, seeded["other_username"], "other-password")
        response = await family_b.get(f"/api/v1/documents/{intent['document_id']}")
        assert response.status_code == 404, response.text
        response = await family_b.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 404, response.text
        response = await family_b.get(preview_url)
        assert response.status_code == 404, response.text
        response = await family_b.post(
            "/api/v1/knowledge/search",
            json={"query": "AAPL"},
            headers=unsafe_headers(family_b),
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []

    async with AsyncSessionLocal() as db:
        family_id = uuid.UUID(seeded["family_a_id"])
        bind_request_context(
            db,
            RequestContext(
                user_id=uuid.UUID(int=0),
                family_id=family_id,
                role="test",
                token_jti=uuid.UUID(int=0),
            ),
        )
        posted = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.idempotency_key.like("document:%"))
                )
            ).scalar_one()
        )
        journals = int((await db.execute(select(func.count()).select_from(JournalEntry))).scalar_one())
        links = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(DocumentLink)
                    .where(DocumentLink.relation == "source_document")
                )
            ).scalar_one()
        )
        holding = (
            await db.execute(
                select(Holding).where(
                    Holding.account_id == uuid.UUID(seeded["account_id"]),
                    Holding.instrument_id == uuid.UUID(seeded["instrument_id"]),
                )
            )
        ).scalar_one()
        audits = int((await db.execute(select(func.count()).select_from(AuditEvent))).scalar_one())
        derived_audits = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.aggregate_type.in_(
                            ("BackgroundJob", "DocumentChunk", "DocumentPage")
                        )
                    )
                )
            ).scalar_one()
        )
        document_tokens = await collect_expected_versions(
            db,
            [
                {
                    "tool": "draft_transactions_from_document",
                    "args": {"document_id": intent["document_id"]},
                }
            ],
        )
        assert posted == 1
        assert journals >= 2  # seed deposit plus confirmed document buy
        assert links == 1
        assert holding.quantity == Decimal(10)
        assert audits > 0
        assert derived_audits == 0
        assert document_tokens[f"documents:{intent['document_id']}"]["exists"] is True
    print(
        "document_rag_integration_ok",
        {
            "job_status": "succeeded",
            "document_status": "ready",
            "posted_document_transactions": posted,
            "document_links": links,
            "holding_quantity": str(holding.quantity),
            "cross_family_document_status": 404,
            "cross_family_job_status": 404,
        },
    )


if __name__ == "__main__":
    asyncio.run(run())
