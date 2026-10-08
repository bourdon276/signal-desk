"""Shared search cache, leases and credit reservations."""

import sqlalchemy as sa
from alembic import op

revision = "20261008_04"
down_revision = "20261006_03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_budgets",
        sa.Column("scope", sa.String(96), primary_key=True),
        sa.Column("credits", sa.Integer(), nullable=False),
    )
    op.create_table(
        "search_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
    )


def downgrade():
    op.drop_table("search_cache")
    op.drop_table("search_budgets")
