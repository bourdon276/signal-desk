"""Initial MVP tables.

Revision ID: 20261001_01
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "20261001_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("watch_id", sa.String(64), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("ingestion_mode", sa.String(30), nullable=False),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_items_watch_published", "items", ["watch_id", "published_at"])
    op.create_table(
        "watches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("watch_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "watch_id"),
    )
    op.create_index("ix_watches_user_id", "watches", ["user_id"])
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_feedback_events_user_id", "feedback_events", ["user_id"])
    op.create_index("ix_feedback_events_item_id", "feedback_events", ["item_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_index("ix_feedback_events_item_id", table_name="feedback_events")
    op.drop_index("ix_feedback_events_user_id", table_name="feedback_events")
    op.drop_table("feedback_events")
    op.drop_index("ix_watches_user_id", table_name="watches")
    op.drop_table("watches")
    op.drop_index("ix_items_watch_published", table_name="items")
    op.drop_table("items")
    op.drop_table("users")
