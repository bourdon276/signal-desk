"""Persist atomic model request reservations."""

import sqlalchemy as sa
from alembic import op

revision = "20261006_03"
down_revision = "20261002_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_budgets",
        sa.Column("scope", sa.String(96), primary_key=True),
        sa.Column("charged_micro_cny", sa.Integer(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("model_budgets")
