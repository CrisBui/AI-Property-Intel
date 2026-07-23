import logging
from functools import lru_cache

from sqlalchemy import select

from property_intel.db.json_utils import as_json_dict, as_json_list
from property_intel.db.models import ListingRow
from property_intel.db.session import session_scope
from property_intel.config import get_settings
from property_intel.llm import (
    augment_system_prompt_for_structured,
    get_chat_model,
    with_structured_output_compat,
)
from property_intel.models.listing import MatchFilters, MatchResult
from property_intel.pipeline.index import _get_collection
from property_intel.pipeline.service_fees_utils import (
    format_water_fee,
    water_filter_mismatch_note,
    water_matches_filter,
)
from property_intel.pipeline.vietnamese_utils import (
    HANOI_DISTRICT_SLUGS,
    normalize_district,
)

logger = logging.getLogger(__name__)

PARSE_FILTERS_PROMPT = """Parse a Vietnamese natural-language rental search query into structured filters.
Think like a rental website filter form + optional free-text notes.

Rules:
- price_max / price_min: monthly rent in VND. Convert "triệu/tr" (4 triệu = 4000000).
  "< 4tr" / "dưới 4 triệu" → price_max=4000000. "> 2 triệu" → price_min=2000000.
- area_min_m2 / area_max_m2: room size in m² when user mentions diện tích.
  ">= 25m2" / "từ 25m2" → area_min_m2=25. "<= 30m2" → area_max_m2=30.
- amenities_required: snake_case room amenities ONLY if explicitly mentioned:
  may_giat, bep, dieu_hoa, nong_lanh, ban_cong. Do NOT infer unstated amenities.
- room_layout_tags: snake_case layout/type ONLY if explicitly mentioned:
  studio, 1_ngu_1_khach, 2_phong_ngu, view_ban_cong, co_bep, gan_thang_may, etc.
  Examples: "phòng studio" → ["studio"]; "1 phòng ngủ riêng" → ["1_ngu_1_khach"].
- district: canonical Hanoi quận when named (Cầu Giấy, Nam Từ Liêm, Đống Đa, …).
- landmark: snake_case POI/khu vực nhỏ (NOT a quận): bach_khoa, dhbk, kim_lien, me_tri, my_dinh.
  "quanh Mễ Trì" → landmark=me_tri (keep district=Nam Từ Liêm if also named).
- soft_prefs: free-text preferences for semantic ranking (yên tĩnh, sáng, gần bus, …).
  Put stylistic/subjective prefs here, NOT hard numeric filters.
- common_amenities_required: building/shared amenities if user asks (thang máy, giữ xe, bảo vệ, …).
  Use plain Vietnamese phrases as stored in common_amenities_json.
- electricity_max_vnd_per_kwh: max electricity fee if mentioned (e.g. "điện dưới 4000đ/kWh" → 4000).
- water_max_vnd_per_m3: max water fee per m³ if user says đ/m3, mét khối, m3.
- water_max_vnd_per_person: max water fee per person if user says đ/người, theo người.
  Do NOT put per-person water limits into water_max_vnd_per_m3 (different units).
- internet_max_vnd_per_room: max internet fee per room if mentioned.
- min_floor_count / max_floor_count: building floors if mentioned ("tòa 5 tầng" → min_floor_count=5).
- min_room_count: minimum rooms in building if mentioned.

Example query:
"Tìm phòng trọ quanh Mễ Trì, Nam Từ Liêm, giá dưới 4 triệu, phòng từ 25m2, studio, yên tĩnh"
→ price_max=4000000, area_min_m2=25, district="Nam Từ Liêm", landmark="me_tri",
  room_layout_tags=["studio"], amenities_required=[], soft_prefs="yên tĩnh"
"""


def _fold_key(text: str) -> str:
    import unicodedata

    from property_intel.pipeline.vietnamese_utils import normalize_unicode

    text = normalize_unicode(text).lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _district_from_landmark_slug(landmark: str) -> str | None:
    slug = landmark.lower().replace("_", "-")
    if slug in HANOI_DISTRICT_SLUGS:
        return HANOI_DISTRICT_SLUGS[slug]
    return None


def normalize_match_filters(filters: MatchFilters) -> MatchFilters:
    """Post-process LLM filters: district slugs, dedupe district vs landmark."""
    district = normalize_district(filters.district)
    landmark = filters.landmark

    if not district and landmark:
        mapped = _district_from_landmark_slug(landmark)
        if mapped:
            district = mapped
            landmark = None

    if district and landmark and _district_from_landmark_slug(landmark) == district:
        landmark = None

    return filters.model_copy(update={"district": district, "landmark": landmark})


def _row_matches_district(row: ListingRow, district: str | None) -> bool:
    if not district:
        return True
    row_district = normalize_district(row.district)
    target = normalize_district(district)
    if not row_district or not target:
        return False
    return _fold_key(row_district) == _fold_key(target)


def _normalize_query_key(query: str) -> str:
    return " ".join(query.strip().split())


def _parse_match_filters_impl(query: str) -> MatchFilters:
    settings = get_settings()
    llm = get_chat_model(settings)
    structured = with_structured_output_compat(llm, MatchFilters, settings)
    filters = structured.invoke(
        [
            {
                "role": "system",
                "content": augment_system_prompt_for_structured(
                    PARSE_FILTERS_PROMPT, settings
                ),
            },
            {"role": "user", "content": query},
        ]
    )
    return normalize_match_filters(filters)


@lru_cache(maxsize=256)
def _parse_match_filters_cached(query_key: str) -> MatchFilters:
    return _parse_match_filters_impl(query_key)


def parse_match_filters(query: str) -> MatchFilters:
    """Parse NL query to filters; cached by normalized query text for stable web/CLI runs."""
    key = _normalize_query_key(query)
    if not key:
        return MatchFilters()
    return _parse_match_filters_cached(key).model_copy()


def clear_parse_filters_cache() -> None:
    _parse_match_filters_cached.cache_clear()


_SERVICE_FEE_LABELS: dict[str, tuple[str, str]] = {
    "electricity_vnd_per_kwh": ("Điện", "đ/kWh"),
    "internet_vnd_per_room": ("Internet", "đ/phòng"),
    "laundry_vnd_per_person": ("Giặt sấy", "đ/người"),
    "other_vnd_per_person": ("DV khác", "đ/người"),
    "sanitation_vnd_per_person": ("Vệ sinh", "đ/người"),
}


def format_service_fee_summary(fees: dict) -> list[str]:
    parts: list[str] = []
    water_line = format_water_fee(fees)
    if water_line:
        parts.append(water_line)
    for key, (label, unit) in _SERVICE_FEE_LABELS.items():
        value = fees.get(key)
        if value is not None and isinstance(value, (int, float)):
            parts.append(f"{label} {int(value):,} {unit}")
    return parts


def _row_has_amenities(row: ListingRow, required: list[str]) -> bool:
    if not required:
        return True
    amenities = set(as_json_list(row.amenities_json))
    return all(a in amenities for a in required)


def _row_has_common_amenities(row: ListingRow, required: list[str]) -> bool:
    if not required:
        return True
    common = [c.lower() for c in as_json_list(row.common_amenities_json)]
    for req in required:
        needle = req.lower()
        if not any(needle in item for item in common):
            return False
    return True


def _row_matches_service_fees(row: ListingRow, filters: MatchFilters) -> bool:
    fees = as_json_dict(row.service_fees_json)
    if filters.electricity_max_vnd_per_kwh is not None:
        actual = fees.get("electricity_vnd_per_kwh")
        if actual is not None and int(actual) > filters.electricity_max_vnd_per_kwh:
            return False
    if not water_matches_filter(
        fees,
        filters.water_max_vnd_per_m3,
        filters.water_max_vnd_per_person,
    ):
        return False
    if filters.internet_max_vnd_per_room is not None:
        actual = fees.get("internet_vnd_per_room")
        if actual is not None and int(actual) > filters.internet_max_vnd_per_room:
            return False
    return True


def _row_matches_building(row: ListingRow, filters: MatchFilters) -> bool:
    building = as_json_dict(row.building_json)
    floor = building.get("floor_count")
    rooms = building.get("room_count")
    if filters.min_floor_count is not None:
        if floor is None or int(floor) < filters.min_floor_count:
            return False
    if filters.max_floor_count is not None:
        if floor is None or int(floor) > filters.max_floor_count:
            return False
    if filters.min_room_count is not None:
        if rooms is None or int(rooms) < filters.min_room_count:
            return False
    return True


def _row_has_room_layout(row: ListingRow, required: list[str]) -> bool:
    if not required:
        return True
    tags = set(as_json_list(row.room_layout_tags_json))
    return all(t in tags for t in required)


def _row_area_bounds(row: ListingRow) -> tuple[float | None, float | None]:
    area_min = row.area_min_m2 if row.area_min_m2 is not None else row.area_m2
    area_max = row.area_max_m2 if row.area_max_m2 is not None else row.area_m2
    if area_min is None:
        return None, area_max
    if area_max is None:
        return area_min, area_min
    return area_min, area_max


def _row_matches_area(row: ListingRow, area_min: float | None, area_max: float | None) -> bool:
    lo, hi = _row_area_bounds(row)
    if area_min is not None:
        effective = hi if hi is not None else lo
        if effective is None or effective < area_min:
            return False
    if area_max is not None:
        effective = lo if lo is not None else hi
        if effective is None or effective > area_max:
            return False
    return True


_LANDMARK_ALIASES: dict[str, list[str]] = {
    "me_tri": ["mễ trì", "me tri", "khu mễ trì"],
    "my_dinh": ["mỹ đình", "my dinh"],
    "bach_khoa": ["bách khoa", "bach khoa", "đhbk", "dhbk"],
    "kim_lien": ["kim liên", "kim lien"],
}


def _row_matches_landmark(row: ListingRow, landmark: str | None) -> bool:
    if not landmark:
        return True
    near_landmarks = as_json_list(row.near_landmarks_json)
    text_blob = " ".join(
        [
            row.title or "",
            row.address_text or "",
            row.district or "",
            " ".join(near_landmarks),
        ]
    ).lower()
    key = landmark.lower()
    candidates = [key, key.replace("_", " ")]
    candidates.extend(_LANDMARK_ALIASES.get(key, []))
    return any(alias in text_blob for alias in candidates)


def sql_filter_listings(filters: MatchFilters) -> list[ListingRow]:
    with session_scope() as session:
        rows = session.scalars(select(ListingRow)).all()
        candidates: list[ListingRow] = []
        for row in rows:
            if filters.price_max is not None:
                if row.price_vnd is None or row.price_vnd > filters.price_max:
                    continue
            if filters.price_min is not None:
                if row.price_vnd is None or row.price_vnd < filters.price_min:
                    continue
            if not _row_matches_area(row, filters.area_min_m2, filters.area_max_m2):
                continue
            if not _row_has_amenities(row, filters.amenities_required):
                continue
            if not _row_has_room_layout(row, filters.room_layout_tags):
                continue
            if not _row_has_common_amenities(row, filters.common_amenities_required):
                continue
            if not _row_matches_service_fees(row, filters):
                continue
            if not _row_matches_building(row, filters):
                continue
            if not _row_matches_district(row, filters.district):
                continue
            if not _row_matches_landmark(row, filters.landmark):
                continue
            candidates.append(row)
        session.expunge_all()
        return candidates


def _load_rows_by_source_ids(source_ids: list[str]) -> dict[str, ListingRow]:
    if not source_ids:
        return {}
    with session_scope() as session:
        rows = session.scalars(
            select(ListingRow).where(ListingRow.source_id.in_(source_ids))
        ).all()
        for row in rows:
            _ = (
                row.title,
                row.price_vnd,
                row.district,
                row.address_text,
                row.amenities_json,
                row.near_landmarks_json,
            )
        session.expunge_all()
        return {row.source_id: row for row in rows}


def _build_rationale(row: ListingRow, filters: MatchFilters, score: float) -> str:
    amenities = as_json_list(row.amenities_json)
    common = as_json_list(row.common_amenities_json)
    parts: list[str] = []

    if filters.price_max is not None and row.price_vnd is not None:
        parts.append(f"Giá {row.price_vnd:,} VND (≤ {filters.price_max:,})")
    elif filters.price_min is not None and row.price_vnd is not None:
        parts.append(f"Giá {row.price_vnd:,} VND (≥ {filters.price_min:,})")
    elif row.price_vnd is not None:
        parts.append(f"Giá {row.price_vnd:,} VND")

    lo, hi = _row_area_bounds(row)
    if lo is not None or hi is not None:
        if lo is not None and hi is not None and lo != hi:
            parts.append(f"Diện tích {lo:g}–{hi:g} m²")
        elif lo is not None:
            parts.append(f"Diện tích {lo:g} m²")

    if filters.amenities_required:
        matched = [a for a in filters.amenities_required if a in amenities]
        parts.append(f"Tiện ích phòng: {', '.join(matched)}")

    layout_tags = as_json_list(row.room_layout_tags_json)
    if filters.room_layout_tags:
        matched_layout = [t for t in filters.room_layout_tags if t in layout_tags]
        parts.append(f"Loại phòng: {', '.join(matched_layout)}")

    if filters.common_amenities_required:
        matched_common = [
            c for c in filters.common_amenities_required
            if any(c.lower() in item.lower() for item in common)
        ]
        if matched_common:
            parts.append(f"Tiện ích chung: {', '.join(matched_common)}")

    fees = as_json_dict(row.service_fees_json)
    if filters.electricity_max_vnd_per_kwh is not None and fees.get("electricity_vnd_per_kwh") is not None:
        parts.append(f"Điện {int(fees['electricity_vnd_per_kwh']):,} đ/kWh")
    water_line = format_water_fee(fees)
    if water_line and (
        filters.water_max_vnd_per_m3 is not None or filters.water_max_vnd_per_person is not None
    ):
        parts.append(water_line)
    mismatch = water_filter_mismatch_note(
        fees,
        filters.water_max_vnd_per_m3,
        filters.water_max_vnd_per_person,
    )
    if mismatch:
        parts.append(mismatch)
    if filters.internet_max_vnd_per_room is not None and fees.get("internet_vnd_per_room") is not None:
        parts.append(f"Internet {int(fees['internet_vnd_per_room']):,} đ/phòng")

    building = as_json_dict(row.building_json)
    if building.get("floor_count") is not None:
        parts.append(f"{building['floor_count']} tầng")
    if building.get("room_count") is not None:
        parts.append(f"{building['room_count']} phòng")

    if filters.district:
        parts.append(f"Quận {filters.district}")

    if filters.landmark:
        parts.append(f"Gần {filters.landmark.replace('_', ' ')}")

    parts.append(f"Chroma score={score:.3f}")
    return "; ".join(parts)


def _row_to_match_result(
    row: ListingRow, filters: MatchFilters, score: float
) -> MatchResult:
    amenities = as_json_list(row.amenities_json)
    landmarks = as_json_list(row.near_landmarks_json)
    layout_tags = as_json_list(row.room_layout_tags_json)
    common = as_json_list(row.common_amenities_json)
    fees = as_json_dict(row.service_fees_json)
    lo, hi = _row_area_bounds(row)
    return MatchResult(
        source_id=row.source_id,
        title=row.title,
        price_vnd=row.price_vnd,
        district=row.district,
        address_text=row.address_text,
        area_min_m2=lo,
        area_max_m2=hi,
        amenities=amenities,
        room_layout_tags=layout_tags,
        common_amenities=common,
        service_fees=fees,
        near_landmarks=landmarks,
        source_url=row.source_url,
        contact_phone=row.contact_phone,
        short_description=row.short_description,
        score=score,
        rationale=_build_rationale(row, filters, score),
    )


def chroma_rerank(
    query: str,
    candidates: list[ListingRow],
    filters: MatchFilters,
    top_k: int = 5,
) -> tuple[list[MatchResult], bool]:
    collection = _get_collection()
    candidate_map = {row.source_id: row for row in candidates}
    used_fallback = not candidates

    chroma_query = query
    if filters.soft_prefs:
        chroma_query = f"{query}. {filters.soft_prefs}"

    if candidates:
        logger.info(
            "Chroma rerank within %d SQL candidates: %s",
            len(candidates),
            sorted(candidate_map.keys()),
        )
        where = {"source_id": {"$in": list(candidate_map.keys())}}
        results = collection.query(
            query_texts=[chroma_query],
            n_results=min(top_k, len(candidates)),
            where=where,
        )
    else:
        logger.warning(
            "SQL filter returned no candidates; falling back to full Chroma search."
        )
        results = collection.query(
            query_texts=[chroma_query],
            n_results=top_k,
        )

    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]

    missing_ids = [doc_id for doc_id in ids if doc_id not in candidate_map]
    if missing_ids:
        candidate_map.update(_load_rows_by_source_ids(missing_ids))

    match_results: list[MatchResult] = []
    for doc_id, distance in zip(ids, distances, strict=False):
        row = candidate_map.get(doc_id)
        if row is None:
            continue
        score = 1.0 / (1.0 + float(distance))
        match_results.append(_row_to_match_result(row, filters, score))

    return match_results[:top_k], used_fallback


def hybrid_match(query: str, top_k: int = 5) -> tuple[MatchFilters, list[MatchResult], bool]:
    filters = parse_match_filters(query)
    logger.info("Parsed filters: %s", filters.model_dump())

    candidates = sql_filter_listings(filters)
    candidate_ids = sorted(row.source_id for row in candidates)
    logger.info("SQL candidates: %d — IDs: %s", len(candidates), candidate_ids)

    results, used_fallback = chroma_rerank(query, candidates, filters, top_k=top_k)
    if used_fallback:
        logger.info("Chroma fallback returned %d results", len(results))
    return filters, results, used_fallback
