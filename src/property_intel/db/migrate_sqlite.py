"""One-shot migration: copy data from SQLite to PostgreSQL."""

import logging
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from property_intel.config import get_settings
from property_intel.db.json_utils import as_json_list
from property_intel.db.models import ListingRow, RawListingRow
from property_intel.db.session import reset_engine, reset_postgres_sequences

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_URL = "sqlite:///./data/app.db"


def _parse_sqlite_url(sqlite_url: str) -> str:
    if not sqlite_url.startswith("sqlite"):
        raise ValueError(f"Expected SQLite URL, got: {sqlite_url}")
    return sqlite_url


def migrate_sqlite_to_postgres(
    sqlite_url: str | None = None,
    postgres_url: str | None = None,
) -> dict[str, int]:
    settings = get_settings()
    src_url = _parse_sqlite_url(sqlite_url or DEFAULT_SQLITE_URL)
    dst_url = postgres_url or settings.database_url

    if not dst_url.startswith("postgresql"):
        raise ValueError(
            "Target DATABASE_URL must be PostgreSQL. "
            f"Set DATABASE_URL in .env or pass postgres_url. Got: {dst_url}"
        )

    sqlite_path = src_url.removeprefix("sqlite:///")
    if not Path(sqlite_path).exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    src_engine = create_engine(src_url, connect_args={"check_same_thread": False})
    dst_engine = create_engine(dst_url, pool_pre_ping=True)

    SrcSession = sessionmaker(bind=src_engine, autoflush=False, autocommit=False)
    DstSession = sessionmaker(bind=dst_engine, autoflush=False, autocommit=False)

    raw_count = 0
    listing_count = 0

    with SrcSession() as src_session, DstSession() as dst_session:
        dst_session.execute(text("TRUNCATE TABLE listings, raw_listings RESTART IDENTITY CASCADE"))

        raw_rows = src_session.scalars(select(RawListingRow).order_by(RawListingRow.id)).all()
        for row in raw_rows:
            dst_session.add(
                RawListingRow(
                    id=row.id,
                    source_id=row.source_id,
                    body=row.body,
                    source_platform=getattr(row, "source_platform", None) or "seed_file",
                    source_url=getattr(row, "source_url", None),
                    crawled_at=getattr(row, "crawled_at", None),
                    last_seen_at=getattr(row, "last_seen_at", None),
                    ingested_at=row.ingested_at,
                    extracted=row.extracted,
                    extract_status=row.extract_status,
                )
            )
            raw_count += 1

        listing_rows = src_session.scalars(select(ListingRow).order_by(ListingRow.id)).all()
        for row in listing_rows:
            dst_session.add(
                ListingRow(
                    id=row.id,
                    source_id=row.source_id,
                    title=row.title,
                    description_raw=row.description_raw,
                    price_vnd=row.price_vnd,
                    area_m2=row.area_m2,
                    district=row.district,
                    address_text=row.address_text,
                    lat=row.lat,
                    lng=row.lng,
                    amenities_json=as_json_list(row.amenities_json),
                    near_landmarks_json=as_json_list(row.near_landmarks_json),
                    sentiment_notes=row.sentiment_notes,
                    extract_confidence=row.extract_confidence,
                    posted_at=row.posted_at,
                    indexed_at=row.indexed_at,
                )
            )
            listing_count += 1

        reset_postgres_sequences(dst_session)
        dst_session.commit()

    src_engine.dispose()
    dst_engine.dispose()
    reset_engine()

    logger.info(
        "Migrated SQLite → Postgres: raw_listings=%d listings=%d",
        raw_count,
        listing_count,
    )
    return {"raw_listings": raw_count, "listings": listing_count}
