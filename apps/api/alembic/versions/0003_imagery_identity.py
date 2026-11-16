"""Add Sentinel-1 product identity and acquisition time fields.

Revision ID: 0003_imagery
Revises: 0002_p0_p1
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_imagery"
down_revision = "0002_p0_p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("s1_product_id", sa.String(200), nullable=False, server_default=""))
    for table in ("tasks", "products"):
        op.add_column(table, sa.Column("acquisition_start", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("acquisition_end", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("s1_product_id", sa.String(200), nullable=False, server_default=""))


def downgrade() -> None:
    for table in ("tasks", "products"):
        op.drop_column(table, "s1_product_id")
        op.drop_column(table, "acquisition_end")
        op.drop_column(table, "acquisition_start")
    op.drop_column("datasets", "s1_product_id")
