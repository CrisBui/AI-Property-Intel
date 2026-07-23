"""Add PhongTot extended listing fields (Option B).

Revision ID: 004
Revises: 003
Create Date: 2026-07-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("source_url", sa.String(length=1024), nullable=True))
    op.add_column("listings", sa.Column("contact_phone", sa.String(length=32), nullable=True))
    op.add_column("listings", sa.Column("short_description", sa.Text(), nullable=True))
    op.add_column("listings", sa.Column("description_long", sa.Text(), nullable=True))
    op.add_column("listings", sa.Column("price_note", sa.String(length=512), nullable=True))
    op.add_column("listings", sa.Column("area_min_m2", sa.Float(), nullable=True))
    op.add_column("listings", sa.Column("area_max_m2", sa.Float(), nullable=True))
    op.add_column(
        "listings",
        sa.Column(
            "service_fees_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "listings",
        sa.Column(
            "common_amenities_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "listings",
        sa.Column(
            "room_layout_tags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "listings",
        sa.Column(
            "building_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("listings", "building_json")
    op.drop_column("listings", "room_layout_tags_json")
    op.drop_column("listings", "common_amenities_json")
    op.drop_column("listings", "service_fees_json")
    op.drop_column("listings", "area_max_m2")
    op.drop_column("listings", "area_min_m2")
    op.drop_column("listings", "price_note")
    op.drop_column("listings", "description_long")
    op.drop_column("listings", "short_description")
    op.drop_column("listings", "contact_phone")
    op.drop_column("listings", "source_url")
