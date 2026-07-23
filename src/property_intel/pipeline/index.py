import logging
from datetime import datetime, timezone

import chromadb
from sqlalchemy import select

from property_intel.config import get_settings
from property_intel.db.json_utils import as_json_list
from property_intel.db.models import ListingRow
from property_intel.db.session import session_scope

logger = logging.getLogger(__name__)

COLLECTION_NAME = "listings"


def _document_text(row: ListingRow) -> str:
    amenities = as_json_list(row.amenities_json)
    layout_tags = as_json_list(row.room_layout_tags_json)
    common = as_json_list(row.common_amenities_json)
    parts = [
        row.title,
        row.district or "",
        row.address_text or "",
        row.short_description or "",
        row.description_long or row.description_raw,
        " ".join(amenities),
        " ".join(layout_tags),
        " ".join(common),
    ]
    return "\n".join(p for p in parts if p)


def _get_collection():
    settings = get_settings()
    settings.chroma_path_resolved.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_path_resolved))
    return client.get_or_create_collection(name=COLLECTION_NAME)


def index_listings() -> dict[str, int]:
    collection = _get_collection()
    indexed = 0

    with session_scope() as session:
        rows = session.scalars(select(ListingRow).order_by(ListingRow.source_id)).all()
        if not rows:
            logger.warning("No listings in database to index.")
            return {"indexed": 0}

        for row in rows:
            doc_id = row.source_id
            try:
                collection.delete(ids=[doc_id])
            except Exception:
                pass

            amenities = as_json_list(row.amenities_json)
            landmarks = as_json_list(row.near_landmarks_json)
            collection.add(
                ids=[doc_id],
                documents=[_document_text(row)],
                metadatas=[
                    {
                        "source_id": row.source_id,
                        "price_vnd": row.price_vnd if row.price_vnd is not None else -1,
                        "district": row.district or "",
                        "amenities": ",".join(amenities),
                        "near_landmarks": ",".join(landmarks),
                    }
                ],
            )
            row.indexed_at = datetime.now(timezone.utc)
            indexed += 1
            logger.info("Indexed %s", row.source_id)

    return {"indexed": indexed}
