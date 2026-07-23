"""Remove crawled listings by source site (e.g. NhaTot)."""

from __future__ import annotations

import logging

import chromadb
from sqlalchemy import delete, select

from property_intel.config import get_settings
from property_intel.db.models import ListingRow, RawListingRow
from property_intel.db.session import session_scope

logger = logging.getLogger(__name__)

COLLECTION_NAME = "listings"


def _delete_from_chroma(source_ids: list[str]) -> int:
    if not source_ids:
        return 0

    settings = get_settings()
    if not settings.chroma_path_resolved.exists():
        return 0

    client = chromadb.PersistentClient(path=str(settings.chroma_path_resolved))
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception:
        return 0

    removed = 0
    batch_size = 100
    for start in range(0, len(source_ids), batch_size):
        batch = source_ids[start : start + batch_size]
        try:
            collection.delete(ids=batch)
            removed += len(batch)
        except Exception as exc:
            logger.warning("Chroma delete batch failed: %s", exc)
    return removed


def purge_nhatot() -> dict[str, int]:
    """Delete NhaTot/Chotot crawl data from raw_listings, listings, and Chroma."""
    with session_scope() as session:
        nhatot_raw = session.scalars(
            select(RawListingRow).where(
                RawListingRow.source_url.ilike("%nhatot.com%")
                | RawListingRow.source_url.ilike("%chotot.com%")
                | RawListingRow.source_platform == "nhatot"
            )
        ).all()
        source_ids = [row.source_id for row in nhatot_raw]

        firecrawl_nhatot_listings = session.scalars(
            select(ListingRow).where(
                ListingRow.source_id.in_(source_ids)
                if source_ids
                else ListingRow.source_id == "__none__"
            )
        ).all()
        listing_ids = {row.source_id for row in firecrawl_nhatot_listings}
        all_source_ids = sorted(set(source_ids) | listing_ids)

        raw_deleted = session.execute(
            delete(RawListingRow).where(
                RawListingRow.source_url.ilike("%nhatot.com%")
                | RawListingRow.source_url.ilike("%chotot.com%")
                | RawListingRow.source_platform == "nhatot"
            )
        ).rowcount

        listings_deleted = 0
        if all_source_ids:
            listings_deleted = session.execute(
                delete(ListingRow).where(ListingRow.source_id.in_(all_source_ids))
            ).rowcount

    chroma_deleted = _delete_from_chroma(all_source_ids)

    stats = {
        "raw_deleted": raw_deleted or 0,
        "listings_deleted": listings_deleted or 0,
        "chroma_deleted": chroma_deleted,
    }
    logger.info("Purge NhaTot complete: %s", stats)
    return stats


def reset_phongtot_for_recrawl() -> dict[str, int]:
    """Delete PhongTot crawl rows so re-crawl uses fresh phongtot_* source_ids."""
    with session_scope() as session:
        rows = session.scalars(
            select(RawListingRow).where(RawListingRow.source_url.ilike("%phongtot.com%"))
        ).all()
        source_ids = [row.source_id for row in rows]

        listings_deleted = 0
        if source_ids:
            listings_deleted = session.execute(
                delete(ListingRow).where(ListingRow.source_id.in_(source_ids))
            ).rowcount

        raw_deleted = session.execute(
            delete(RawListingRow).where(RawListingRow.source_url.ilike("%phongtot.com%"))
        ).rowcount

    chroma_deleted = _delete_from_chroma(source_ids)

    stats = {
        "raw_deleted": raw_deleted or 0,
        "listings_deleted": listings_deleted or 0,
        "chroma_deleted": chroma_deleted,
    }
    logger.info("PhongTot reset for re-crawl: %s", stats)
    return stats


def purge_legacy_data() -> dict[str, int]:
    """Remove seed, firecrawl, url_fetch, nhatot — keep only PhongTot crawl data."""
    legacy_platforms = ("seed_file", "firecrawl", "url_fetch", "nhatot")

    with session_scope() as session:
        rows = session.scalars(
            select(RawListingRow).where(
                RawListingRow.source_platform.in_(legacy_platforms)
                | RawListingRow.source_id.like("tr%")
                | RawListingRow.source_id.like("firecrawl_%")
                | RawListingRow.source_id.like("url_fetch_%")
            )
        ).all()
        source_ids = [row.source_id for row in rows]

        listing_rows = session.scalars(
            select(ListingRow).where(
                ListingRow.source_id.in_(source_ids)
                if source_ids
                else ListingRow.source_id == "__none__"
            )
        ).all()
        all_source_ids = sorted(set(source_ids) | {r.source_id for r in listing_rows})

        raw_deleted = session.execute(
            delete(RawListingRow).where(
                RawListingRow.source_platform.in_(legacy_platforms)
                | RawListingRow.source_id.like("tr%")
                | RawListingRow.source_id.like("firecrawl_%")
                | RawListingRow.source_id.like("url_fetch_%")
            )
        ).rowcount

        listings_deleted = 0
        if all_source_ids:
            listings_deleted = session.execute(
                delete(ListingRow).where(ListingRow.source_id.in_(all_source_ids))
            ).rowcount

    chroma_deleted = _delete_from_chroma(all_source_ids)

    stats = {
        "raw_deleted": raw_deleted or 0,
        "listings_deleted": listings_deleted or 0,
        "chroma_deleted": chroma_deleted,
    }
    logger.info("Purge legacy (non-PhongTot) complete: %s", stats)
    return stats
