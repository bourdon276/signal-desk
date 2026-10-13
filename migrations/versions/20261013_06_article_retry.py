"""Persist bounded article enrichment retries across service restarts."""
import sqlalchemy as sa
from alembic import op

revision = "20261013_06"
down_revision = "20261011_05"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("items", sa.Column("article_retry_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("items", sa.Column("article_last_error", sa.String(50), nullable=True))


def downgrade():
    op.drop_column("items", "article_last_error")
    op.drop_column("items", "article_retry_after")
