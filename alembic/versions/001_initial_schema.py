"""Initial schema: raw_listings and listings.

Revision ID: 001
Revises:
Create Date: 2026-07-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raw_listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("extracted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extract_status", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description_raw", sa.Text(), nullable=False),
        sa.Column("price_vnd", sa.Integer(), nullable=True),
        sa.Column("area_m2", sa.Float(), nullable=True),
        sa.Column("district", sa.String(length=128), nullable=True),
        sa.Column("address_text", sa.String(length=512), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column(
            "amenities_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "near_landmarks_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sentiment_notes", sa.Text(), nullable=True),
        sa.Column(
            "extract_confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )


def downgrade() -> None:
    op.drop_table("listings")
    op.drop_table("raw_listings")
