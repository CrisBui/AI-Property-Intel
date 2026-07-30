import logging
import re
import time

from pydantic import BaseModel, Field
from sqlalchemy import select

from property_intel.config import get_settings
from property_intel.db.models import ListingRow, RawListingRow
from property_intel.db.session import session_scope
from property_intel.llm import (
    augment_system_prompt_for_structured,
    get_chat_model,
    with_structured_output_compat,
)
from property_intel.models.listing import Listing
from property_intel.pipeline.crawl.body_utils import prepare_body_for_llm
from property_intel.pipeline.nhatot_parser import extract_nhatot_main_content, parse_nhatot_body
from property_intel.pipeline.phongtot_parser import extract_phongtot_main_content, parse_phongtot_body
from property_intel.pipeline.listing_media import extract_image_urls
from property_intel.pipeline.freshness import parse_posted_at
from property_intel.pipeline.vietnamese_utils import normalize_district, normalize_amenities

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """You extract structured rental listing data from messy Vietnamese rental posts.

Rules:
- source_id must match the provided value exactly.
- If price is unclear, set price_vnd to null. Convert "triệu", "tr", "m" to VND (1 triệu = 1_000_000, 1tr5 = 1500000, 1m5 = 1500000).
- Normalize amenities to snake_case from this set only when clearly mentioned:
  may_giat, bep, dieu_hoa, nong_lanh, ban_cong
- room_layout_tags: snake_case tags when clearly mentioned, e.g. studio, 1_ngu_1_khach, 2_phong_ngu, view_ban_cong, co_bep, gan_thang_may
- Normalize near_landmarks to snake_case (e.g. bach_khoa, dhbk, kim_lien, dong_tac, lang_ha).
- extract_confidence: 0.0-1.0 based on clarity of extracted fields.
- short_description: 2-3 câu tiếng Việt tóm tắt vị trí, loại phòng, tiện ích nổi bật, giá (nếu có). Giữ đúng dấu UTF-8.
- Do NOT return the full raw post text; only structured fields.
- Keep title plain text without markdown or escape characters.
- For Vietnamese text: preserve correct diacritics exactly as in source (UTF-8), e.g. Cầu Giấy, Nam Từ Liêm, Nguyễn.
- Prefer copying title, district, and address verbatim from the source when present.
"""


class ListingExtraction(BaseModel):
    """Structured output schema for LLM extraction (no description_raw — injected from raw file)."""

    source_id: str = Field(description="Unique listing id from filename")
    title: str
    price_vnd: int | None = None
    area_m2: float | None = None
    district: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    amenities: list[str] = Field(default_factory=list)
    near_landmarks: list[str] = Field(default_factory=list)
    room_layout_tags: list[str] = Field(default_factory=list)
    short_description: str | None = None
    sentiment_notes: str | None = None
    extract_confidence: float = 0.0


def _fallback_short_description(
    result: ListingExtraction,
    parsed,
) -> str | None:
    """Template summary when LLM summary is disabled or empty (no extra API call)."""
    parts: list[str] = []
    if result.title:
        parts.append(result.title)
    if result.district:
        parts.append(f"Khu vực {result.district}.")
    if result.price_vnd:
        parts.append(f"Giá từ {result.price_vnd:,} VND/tháng.")
    if parsed is not None and parsed.common_amenities:
        parts.append("Tiện ích: " + ", ".join(parsed.common_amenities[:4]) + ".")
    if result.amenities:
        parts.append("Phòng có: " + ", ".join(result.amenities) + ".")
    text = " ".join(parts).strip()
    return text[:500] if text else None


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "429" in message or "too many requests" in message or "rate limit" in message


def _is_retryable_llm_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if _is_rate_limit_error(exc):
        return True
    if "tool_use_failed" in message or "failed to call a function" in message:
        return True
    # Do not retry plain 400 Bad Request (schema/validation) — wastes quota
    if "400" in message and "bad request" in message:
        return False
    return False


def _retry_delay_seconds(attempt: int, base_delay: float, exc: Exception) -> float:
    """Exponential backoff; honour Retry-After hints when Groq sends them."""
    delay = base_delay * (2 ** attempt)
    match = re.search(r"retry(?:ing)?(?: request)? in (\d+(?:\.\d+)?)", str(exc), re.I)
    if match:
        delay = max(delay, float(match.group(1)))
    return min(delay, 120.0)


def _invoke_structured(structured_llm, messages: list[dict], settings) -> ListingExtraction:
    last_exc: Exception | None = None
    for attempt in range(settings.extract_max_retries):
        try:
            return structured_llm.invoke(messages)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_llm_error(exc) or attempt >= settings.extract_max_retries - 1:
                raise
            delay = _retry_delay_seconds(
                attempt,
                settings.extract_rate_limit_seconds,
                exc,
            )
            logger.warning(
                "LLM retry %d/%d in %.1fs (%s)",
                attempt + 1,
                settings.extract_max_retries,
                delay,
                type(exc).__name__,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _resolve_short_description(
    result: ListingExtraction,
    parsed,
    settings,
) -> str | None:
    if settings.extract_enable_llm_summary and result.short_description:
        return normalize_unicode_text(result.short_description)
    return _fallback_short_description(result, parsed)


def _invoke_structured_generic(structured_llm, messages: list[dict], settings):
    last_exc: Exception | None = None
    for attempt in range(settings.extract_max_retries):
        try:
            return structured_llm.invoke(messages)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_llm_error(exc) or attempt >= settings.extract_max_retries - 1:
                raise
            time.sleep(_retry_delay_seconds(attempt, settings.extract_rate_limit_seconds, exc))
    assert last_exc is not None
    raise last_exc


def _listing_to_row(listing: Listing) -> ListingRow:
    area_m2 = listing.area_m2
    if area_m2 is None and listing.area_min_m2 is not None:
        area_m2 = listing.area_min_m2
    return ListingRow(
        source_id=listing.source_id,
        title=listing.title,
        description_raw=listing.description_raw,
        price_vnd=listing.price_vnd,
        area_m2=area_m2,
        area_min_m2=listing.area_min_m2,
        area_max_m2=listing.area_max_m2,
        district=listing.district,
        address_text=listing.address_text,
        lat=listing.lat,
        lng=listing.lng,
        amenities_json=list(listing.amenities),
        near_landmarks_json=list(listing.near_landmarks),
        common_amenities_json=list(listing.common_amenities),
        room_layout_tags_json=list(listing.room_layout_tags),
        service_fees_json=dict(listing.service_fees),
        building_json=dict(listing.building),
        source_url=listing.source_url,
        contact_phone=listing.contact_phone,
        short_description=listing.short_description,
        description_long=listing.description_long,
        price_note=listing.price_note,
        images_json=list(listing.images),
        sentiment_notes=listing.sentiment_notes,
        extract_confidence=listing.extract_confidence,
        posted_at=listing.posted_at,
    )


def _upsert_listing(session, listing: Listing) -> None:
    row = session.scalar(
        select(ListingRow).where(ListingRow.source_id == listing.source_id)
    )
    if row is None:
        session.add(_listing_to_row(listing))
        return

    row.title = listing.title
    row.description_raw = listing.description_raw
    row.price_vnd = listing.price_vnd
    row.area_m2 = listing.area_m2 or listing.area_min_m2
    row.area_min_m2 = listing.area_min_m2
    row.area_max_m2 = listing.area_max_m2
    row.district = listing.district
    row.address_text = listing.address_text
    row.lat = listing.lat
    row.lng = listing.lng
    row.amenities_json = list(listing.amenities)
    row.near_landmarks_json = list(listing.near_landmarks)
    row.common_amenities_json = list(listing.common_amenities)
    row.room_layout_tags_json = list(listing.room_layout_tags)
    row.service_fees_json = dict(listing.service_fees)
    row.building_json = dict(listing.building)
    row.source_url = listing.source_url
    row.contact_phone = listing.contact_phone
    row.short_description = listing.short_description
    row.description_long = listing.description_long
    row.price_note = listing.price_note
    row.images_json = list(listing.images)
    row.sentiment_notes = listing.sentiment_notes
    row.extract_confidence = listing.extract_confidence
    row.posted_at = listing.posted_at
    row.indexed_at = None


def _merge_phongtot_fields(result: ListingExtraction, parsed, source_url: str | None) -> ListingExtraction:
    """Prefer deterministic PhongTot parser over LLM for text-heavy fields."""
    data = result.model_dump()
    if parsed.title:
        data["title"] = parsed.title
    if parsed.price_vnd_min is not None:
        data["price_vnd"] = parsed.price_vnd_min
    if parsed.address_text:
        data["address_text"] = parsed.address_text
    if parsed.district:
        data["district"] = parsed.district
    else:
        data["district"] = normalize_district(data.get("district"))
    if data.get("district"):
        data["district"] = normalize_district(data["district"])
    if data.get("title"):
        data["title"] = normalize_unicode_text(data["title"])
    return ListingExtraction(**data)


def _merge_nhatot_fields(result: ListingExtraction, parsed, source_url: str | None) -> ListingExtraction:
    """Prefer deterministic NhaTot parser over LLM for text-heavy fields."""
    data = result.model_dump()
    if parsed.title:
        data["title"] = parsed.title
    if parsed.price_vnd_min is not None:
        data["price_vnd"] = parsed.price_vnd_min
    if parsed.address_text:
        data["address_text"] = parsed.address_text
    if parsed.district:
        data["district"] = parsed.district
    elif data.get("district"):
        data["district"] = normalize_district(data["district"])
    if parsed.area_min_m2 is not None and data.get("area_m2") is None:
        data["area_m2"] = parsed.area_min_m2
    if data.get("district"):
        data["district"] = normalize_district(data["district"])
    if data.get("title"):
        data["title"] = normalize_unicode_text(data["title"])
    return ListingExtraction(**data)


def normalize_unicode_text(text: str) -> str:
    from property_intel.pipeline.vietnamese_utils import normalize_unicode

    return normalize_unicode(text)


def _build_listing_from_extract(
    raw: RawListingRow,
    result: ListingExtraction,
    parsed,
    body_for_llm: str,
    settings,
) -> Listing:
    listing_kwargs: dict = {
        "source_id": raw.source_id,
        "title": result.title,
        "description_raw": body_for_llm,
        "price_vnd": result.price_vnd,
        "area_m2": result.area_m2,
        "district": result.district,
        "address_text": result.address_text,
        "lat": result.lat,
        "lng": result.lng,
        "amenities": normalize_amenities(result.amenities),
        "near_landmarks": result.near_landmarks,
        "room_layout_tags": result.room_layout_tags,
        "short_description": _resolve_short_description(result, parsed, settings),
        "sentiment_notes": result.sentiment_notes,
        "extract_confidence": result.extract_confidence,
        "posted_at": None,
        "source_url": raw.source_url,
    }

    if parsed is not None:
        common_amenities = list(getattr(parsed, "common_amenities", []) or [])
        furnishing = getattr(parsed, "furnishing", None)
        if furnishing and furnishing not in common_amenities:
            common_amenities.append(furnishing)
        listing_kwargs.update(
            {
                "common_amenities": common_amenities,
                "service_fees": parsed.service_fees,
                "building": {
                    "floor_count": getattr(parsed, "floor_count", None),
                    "room_count": getattr(parsed, "room_count", None),
                    "renovation_year": getattr(parsed, "renovation_year", None),
                    "deposit_vnd": getattr(parsed, "deposit_vnd", None),
                },
                "contact_phone": parsed.contact_phone,
                "description_long": parsed.description_long,
                "area_min_m2": parsed.area_min_m2,
                "area_max_m2": parsed.area_max_m2,
                "price_note": getattr(parsed, "price_note", None),
            }
        )

    if "images" not in listing_kwargs:
        listing_kwargs["images"] = extract_image_urls(
            raw.body, source_platform=raw.source_platform
        )

    return Listing(**listing_kwargs)


def _extract_one(
    source_id: str,
    structured_llm,
    rate_limit_seconds: float,
    settings,
    force: bool = False,
) -> str:
    """Extract a single raw listing. Returns 'success', 'failed', or 'skipped'."""

    with session_scope() as session:
        raw = session.scalar(
            select(RawListingRow).where(RawListingRow.source_id == source_id)
        )
        if raw is None or (raw.extracted and not force):
            return "skipped"

        try:
            if rate_limit_seconds > 0:
                time.sleep(rate_limit_seconds)

            is_phongtot = raw.source_platform == "phongtot"
            is_nhatot = raw.source_platform == "nhatot"
            raw_body = raw.body
            if is_phongtot:
                raw_body = extract_phongtot_main_content(raw.body)
            elif is_nhatot:
                raw_body = extract_nhatot_main_content(raw.body)
            body_for_llm = prepare_body_for_llm(
                raw_body,
                max_chars=settings.extract_max_body_chars,
                source_platform=raw.source_platform,
            )
            if is_phongtot:
                parsed = parse_phongtot_body(raw.body, raw.source_url)
            elif is_nhatot:
                parsed = parse_nhatot_body(raw.body, raw.source_url)
            else:
                parsed = None
            prompt = (
                f"source_id: {raw.source_id}\n\n"
                f"Raw post:\n{body_for_llm}\n\n"
                "Extract structured fields only."
            )
            result: ListingExtraction = _invoke_structured(
                structured_llm,
                [
                    {
                        "role": "system",
                        "content": augment_system_prompt_for_structured(
                            EXTRACT_SYSTEM_PROMPT, settings
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                settings,
            )
            if parsed is not None:
                if is_phongtot:
                    result = _merge_phongtot_fields(result, parsed, raw.source_url)
                elif is_nhatot:
                    result = _merge_nhatot_fields(result, parsed, raw.source_url)
            else:
                result = ListingExtraction(
                    **{
                        **result.model_dump(),
                        "district": normalize_district(result.district),
                        "title": normalize_unicode_text(result.title),
                    }
                )
            listing = _build_listing_from_extract(
                raw, result, parsed, body_for_llm, settings
            )
            reference_at = raw.last_seen_at or raw.crawled_at
            posted_at = parse_posted_at(raw.body, reference_at)
            if posted_at is not None:
                listing = listing.model_copy(update={"posted_at": posted_at})
            if not listing.images:
                listing = listing.model_copy(
                    update={
                        "images": extract_image_urls(
                            raw.body, source_platform=raw.source_platform
                        )
                    }
                )
            _upsert_listing(session, listing)
            raw.extracted = True
            raw.extract_status = "success"
            logger.info(
                "Extracted %s (confidence=%.2f)",
                raw.source_id,
                listing.extract_confidence,
            )
            return "success"
        except Exception as exc:
            raw.extract_status = "error"
            raw.extracted = False
            if _is_rate_limit_error(exc):
                logger.warning("Rate limited on %s — re-run extract later", raw.source_id)
            else:
                logger.exception("Failed to extract %s: %s", raw.source_id, exc)
            return "failed"


def extract_listings(
    batch_size: int = 50,
    rate_limit_seconds: float | None = None,
    platform: str | None = None,
    force: bool = False,
    enable_llm_summary: bool | None = None,
) -> dict[str, int]:
    settings = get_settings()
    if enable_llm_summary is not None:
        settings = settings.model_copy(update={"extract_enable_llm_summary": enable_llm_summary})
    delay = (
        rate_limit_seconds
        if rate_limit_seconds is not None
        else settings.extract_rate_limit_seconds
    )

    llm = get_chat_model()
    structured_llm = with_structured_output_compat(llm, ListingExtraction, settings)

    success = 0
    failed = 0
    skipped = 0

    while True:
        with session_scope() as session:
            query = (
                select(RawListingRow.source_id)
                .order_by(RawListingRow.source_id)
                .limit(batch_size)
            )
            if platform:
                query = query.where(RawListingRow.source_platform == platform)
            if not force:
                query = query.where(RawListingRow.extracted.is_(False))

            pending_ids = list(session.scalars(query).all())

        if not pending_ids:
            if success == 0 and failed == 0:
                logger.info("No pending raw listings to extract.")
            break

        for source_id in pending_ids:
            outcome = _extract_one(source_id, structured_llm, delay, settings, force=force)
            if outcome == "success":
                success += 1
            elif outcome == "failed":
                failed += 1
            else:
                skipped += 1

        if force or len(pending_ids) < batch_size:
            break

    return {"success": success, "failed": failed, "skipped": skipped}
