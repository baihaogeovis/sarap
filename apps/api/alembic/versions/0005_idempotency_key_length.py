"""Widen auto idempotency_key to include scene_id.

Revision ID: 0005_idem
Revises: 0004_valid
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_idem"
down_revision = "0004_valid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tasks",
        "idempotency_key",
        existing_type=sa.String(200),
        type_=sa.String(512),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "tasks",
        "idempotency_key",
        existing_type=sa.String(512),
        type_=sa.String(200),
        existing_nullable=True,
    )
