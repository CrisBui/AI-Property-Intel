import logging
from pathlib import Path

from sqlalchemy import select

from property_intel.config import get_settings
from property_intel.db.models import RawListingRow
from property_intel.db.session import session_scope

logger = logging.getLogger(__name__)


def ingest_raw_listings(raw_dir: Path | None = None) -> dict[str, int]:
    settings = get_settings()
    directory = raw_dir or settings.raw_data_dir_resolved
    if not directory.exists():
        raise FileNotFoundError(f"Raw data directory not found: {directory}")

    inserted = 0
    updated = 0
    skipped = 0

    txt_files = sorted(directory.glob("*.txt"))
    if not txt_files:
        logger.warning("No .txt files found in %s", directory)

    with session_scope() as session:
        for path in txt_files:
            source_id = path.stem
            body = path.read_text(encoding="utf-8").strip()
            if not body:
                skipped += 1
                continue

            existing = session.scalar(
                select(RawListingRow).where(RawListingRow.source_id == source_id)
            )
            if existing is None:
                session.add(
                    RawListingRow(
                        source_id=source_id,
                        body=body,
                        source_platform="seed_file",
                        extracted=False,
                        extract_status="pending",
                    )
                )
                inserted += 1
            elif existing.body != body:
                existing.body = body
                existing.extracted = False
                existing.extract_status = "pending"
                updated += 1
            else:
                skipped += 1

    total = inserted + updated + skipped
    logger.info(
        "Ingest complete: inserted=%d updated=%d skipped=%d total_files=%d",
        inserted,
        updated,
        skipped,
        total,
    )
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": total}
