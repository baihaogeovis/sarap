"""Allow empty baseline validity bounds (unrestricted).

Revision ID: 0004_valid
Revises: 0003_imagery
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_valid"
down_revision = "0003_imagery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "data_asset_versions",
        "valid_from",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "data_asset_versions",
        "valid_from",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
