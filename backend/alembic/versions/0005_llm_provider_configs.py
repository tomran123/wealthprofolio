"""add encrypted llm provider configurations

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-21
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("provider_key", sa.String(length=30), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_llm_provider_configs_role", "llm_provider_configs", ["role"])
    op.create_index("ix_llm_provider_configs_is_active", "llm_provider_configs", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_llm_provider_configs_is_active", table_name="llm_provider_configs")
    op.drop_index("ix_llm_provider_configs_role", table_name="llm_provider_configs")
    op.drop_table("llm_provider_configs")
