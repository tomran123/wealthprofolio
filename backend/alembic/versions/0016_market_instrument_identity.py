"""Enforce one canonical market instrument per family identity.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provider identity covers symbols that are not globally unique (notably
    # CoinGecko assets). The normalized symbol/market identity closes every
    # other API or import path that could bypass the application advisory lock.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_instruments_family_market_provider
        ON instruments (
            family_id,
            ((external_ids ->> 'price_provider')),
            ((external_ids ->> 'provider_symbol'))
        )
        WHERE price_source_type = 'market'
          AND external_ids ->> 'price_provider' IS NOT NULL
          AND external_ids ->> 'provider_symbol' IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_instruments_family_market_symbol
        ON instruments (family_id, symbol, market)
        WHERE price_source_type = 'market'
          AND symbol IS NOT NULL
          AND COALESCE(external_ids ->> 'price_provider', '') <> 'coingecko'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_instruments_family_market_symbol")
    op.execute("DROP INDEX IF EXISTS uq_instruments_family_market_provider")
