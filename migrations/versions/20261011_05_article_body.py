"""Cache public article bodies separately from source snippets."""
import sqlalchemy as sa
from alembic import op

revision = "20261011_05"
down_revision = "20261008_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("items", sa.Column("article_body", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("body_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("items", "body_fetched_at")
    op.drop_column("items", "article_body")
