"""seed placeholder fx rates

These rows exist so cross-currency aggregation works immediately on a fresh install.
They are intentionally rough/illustrative (source_provider='seed_placeholder') and
should be replaced by real rates once the Phase 2 automatic FX refresh is built, or
updated manually via POST /api/fx-rates in the meantime.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21

"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SEED_RATES = [
    ("USD", "CNY", "7.20"),
    ("USD", "HKD", "7.80"),
    ("USD", "EUR", "0.92"),
]


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    conn = op.get_bind()
    for base, quote, rate in SEED_RATES:
        conn.execute(
            sa.text(
                """
                INSERT INTO fx_rate_snapshots
                    (id, base_currency, quote_currency, rate, as_of, fetched_at, source_provider)
                VALUES (:id, :base, :quote, :rate, :as_of, :fetched_at, 'seed_placeholder')
                """
            ),
            {"id": str(uuid.uuid4()), "base": base, "quote": quote, "rate": rate, "as_of": now, "fetched_at": now},
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM fx_rate_snapshots WHERE source_provider = 'seed_placeholder'"))
