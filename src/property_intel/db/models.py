from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_json_list_type = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class RawListingRow(Base):
    __tablename__ = "raw_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(
        String(32), default="seed_file", nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    extracted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extract_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ListingRow(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    price_vnd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_min_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_max_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    amenities_json: Mapped[list] = mapped_column(
        _json_list_type, default=list, nullable=False
    )
    near_landmarks_json: Mapped[list] = mapped_column(
        _json_list_type, default=list, nullable=False
    )
    common_amenities_json: Mapped[list] = mapped_column(
        _json_list_type, default=list, nullable=False
    )
    room_layout_tags_json: Mapped[list] = mapped_column(
        _json_list_type, default=list, nullable=False
    )
    service_fees_json: Mapped[dict] = mapped_column(
        _json_list_type, default=dict, nullable=False
    )
    building_json: Mapped[dict] = mapped_column(
        _json_list_type, default=dict, nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_long: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sentiment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
