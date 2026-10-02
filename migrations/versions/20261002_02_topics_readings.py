"""Personal topics and explicit reading state."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_02"
down_revision = "20261001_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "topics",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_topics_user_id", "topics", ["user_id"])
    op.create_table(
        "readings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "item_id"),
    )
    op.create_index("ix_readings_user_id", "readings", ["user_id"])


def downgrade():
    op.drop_table("readings")
    op.drop_table("topics")
