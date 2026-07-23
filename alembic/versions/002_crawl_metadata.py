"""Add crawl metadata columns to raw_listings.

Revision ID: 002
Revises: 001
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_listings",
        sa.Column(
            "source_platform",
            sa.String(length=32),
            nullable=False,
            server_default="seed_file",
        ),
    )
    op.add_column(
        "raw_listings",
        sa.Column("source_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "raw_listings",
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "raw_listings",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_listings", "last_seen_at")
    op.drop_column("raw_listings", "crawled_at")
    op.drop_column("raw_listings", "source_url")
    op.drop_column("raw_listings", "source_platform")
