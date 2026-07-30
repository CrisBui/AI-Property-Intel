from __future__ import annotations

from sqlalchemy import select

from property_intel.api.schemas import (
    DescriptionSection,
    ListingCard,
    ListingDetail,
    SearchRequest,
    SearchResponse,
    SearchSort,
)
from property_intel.db.json_utils import as_json_dict, as_json_list
from property_intel.db.models import ListingRow, RawListingRow
from property_intel.db.session import session_scope
from property_intel.models.listing import MatchFilters
from property_intel.pipeline.match_query import (
    _row_area_bounds,
    format_service_fee_summary,
    sql_filter_listings,
)
from property_intel.pipeline.crawl.base import platform_from_source_id, platform_from_url
from property_intel.pipeline.listing_media import extract_image_urls, parse_description_sections
from property_intel.pipeline.vietnamese_utils import normalize_district


def search_request_to_filters(request: SearchRequest) -> MatchFilters:
    districts = [normalize_district(d) or d for d in request.districts if d.strip()]
    districts = [d for d in districts if d]
    return MatchFilters(
        districts=districts,
        price_min=request.price_min,
        price_max=request.price_max,
        area_min_m2=request.area_min_m2,
        area_max_m2=request.area_max_m2,
        room_layout_tags=list(request.room_layout_tags),
        amenities_required=list(request.amenities_required),
        common_amenities_required=list(request.common_amenities_required),
        electricity_max_vnd_per_kwh=request.electricity_max_vnd_per_kwh,
        water_max_vnd_per_m3=request.water_max_vnd_per_m3,
        water_max_vnd_per_person=request.water_max_vnd_per_person,
        internet_max_vnd_per_room=request.internet_max_vnd_per_room,
    )


def _sort_key(row: ListingRow, sort: SearchSort):
    if sort in ("price_asc", "price_desc"):
        missing = row.price_vnd is None
        value = row.price_vnd if row.price_vnd is not None else (-1 if sort == "price_desc" else 10**15)
        return (missing, value)
    lo, _hi = _row_area_bounds(row)
    if sort in ("area_asc", "area_desc"):
        missing = lo is None
        value = lo if lo is not None else (-1 if sort == "area_desc" else 10**9)
        return (missing, value)
    return (True, 0)


def sort_listing_rows(rows: list[ListingRow], sort: SearchSort) -> list[ListingRow]:
    reverse = sort in ("price_desc", "area_desc")
    return sorted(rows, key=lambda row: _sort_key(row, sort), reverse=reverse)


def _resolve_source_platform(row: ListingRow) -> str:
    if row.source_url:
        platform = platform_from_url(row.source_url)
        if platform in {"phongtot", "nhatot"}:
            return platform
    return platform_from_source_id(row.source_id)


def _resolve_listing_images(row: ListingRow, raw_body: str | None = None) -> list[str]:
    stored = as_json_list(getattr(row, "images_json", None) or [])
    if stored:
        return stored
    if raw_body:
        platform = _resolve_source_platform(row)
        return extract_image_urls(raw_body, source_platform=platform)
    return []


def listing_row_to_card(row: ListingRow, images: list[str] | None = None) -> ListingCard:
    fees = as_json_dict(row.service_fees_json)
    lo, hi = _row_area_bounds(row)
    photo_list = images if images is not None else _resolve_listing_images(row)
    return ListingCard(
        source_id=row.source_id,
        title=row.title,
        district=row.district,
        address_text=row.address_text,
        price_vnd=row.price_vnd,
        area_min_m2=lo,
        area_max_m2=hi,
        room_layout_tags=as_json_list(row.room_layout_tags_json),
        amenities=as_json_list(row.amenities_json),
        common_amenities=as_json_list(row.common_amenities_json),
        service_fees_summary=format_service_fee_summary(fees),
        contact_phone=row.contact_phone,
        source_url=row.source_url,
        source_platform=_resolve_source_platform(row),
        short_description=row.short_description,
        thumbnail_url=photo_list[0] if photo_list else None,
    )


def listing_row_to_detail(row: ListingRow, raw_body: str | None = None) -> ListingDetail:
    fees = as_json_dict(row.service_fees_json)
    building_raw = as_json_dict(row.building_json)
    building: dict[str, int | None] = {}
    for key in ("floor_count", "room_count", "renovation_year", "deposit_vnd"):
        val = building_raw.get(key)
        building[key] = int(val) if val is not None else None
    images = _resolve_listing_images(row, raw_body=raw_body)
    card = listing_row_to_card(row, images=images)
    desc = row.description_long or row.short_description
    sections = [
        DescriptionSection(label=section.get("label"), body=section.get("body") or "")
        for section in parse_description_sections(desc)
        if section.get("body")
    ]
    return ListingDetail(
        **card.model_dump(),
        description_long=row.description_long,
        description_sections=sections,
        price_note=row.price_note,
        near_landmarks=as_json_list(row.near_landmarks_json),
        service_fees=fees,
        building=building,
        images=images,
    )


def get_listing_by_source_id(source_id: str) -> ListingDetail | None:
    with session_scope() as session:
        row = session.scalar(
            select(ListingRow).where(ListingRow.source_id == source_id)
        )
        if row is None:
            return None
        raw_row = session.scalar(
            select(RawListingRow).where(RawListingRow.source_id == source_id)
        )
        session.expunge(row)
        raw_body = raw_row.body if raw_row is not None else None
        return listing_row_to_detail(row, raw_body=raw_body)


def search_listings(request: SearchRequest) -> SearchResponse:
    filters = search_request_to_filters(request)
    rows = sql_filter_listings(filters, q=request.q)
    rows = sort_listing_rows(rows, request.sort)
    total = len(rows)
    start = (request.page - 1) * request.size
    end = start + request.size
    page_rows = rows[start:end]
    return SearchResponse(
        total=total,
        page=request.page,
        size=request.size,
        sort=request.sort,
        filters_applied=filters,
        items=[listing_row_to_card(row) for row in page_rows],
    )
