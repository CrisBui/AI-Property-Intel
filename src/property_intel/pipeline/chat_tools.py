"""Helpers for multi-turn chat agent (filter merge, result mapping)."""

from __future__ import annotations

import re

from property_intel.api.schemas import ListingCard, ListingDetail, SearchPageContext
from property_intel.models.listing import MatchFilters, MatchResult
from property_intel.pipeline.crawl.base import platform_from_source_id
from property_intel.pipeline.match_query import format_service_fee_summary
from property_intel.pipeline.search_service import get_listing_by_source_id
from property_intel.pipeline.vietnamese_utils import HANOI_DISTRICT_SLUGS, normalize_unicode


def _fold_key(text: str) -> str:
    import unicodedata

    text = normalize_unicode(text).lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


_PAGE_SCOPED_MARKERS = (
    "đang hiển thị",
    "đang xem",
    "trên màn hình",
    "kết quả này",
    "các phòng này",
    "những phòng này",
    "trang này",
    "list này",
    "màn hình này",
)


def is_page_scoped_request(user_text: str) -> bool:
    """True when user refers to listings currently visible on the search UI page."""
    lowered = _fold_key(user_text)
    if any(marker in lowered for marker in _PAGE_SCOPED_MARKERS):
        return True
    if re.search(r"so\s*sanh", lowered) and not has_location_or_filter_cues(user_text):
        return True
    return False


def has_location_or_filter_cues(user_text: str) -> bool:
    lowered = _fold_key(user_text)
    if "quan" in lowered or "khu vuc" in lowered:
        return True
    for canonical in HANOI_DISTRICT_SLUGS.values():
        if _fold_key(canonical) in lowered:
            return True
    filter_cues = (
        "tim ",
        "co nhung",
        "liet ke",
        "bao nhieu can",
        "cac tro",
        "phong tro",
        "duoi ",
        "tren ",
        "trieu",
        "trieu/",
        "m2",
        "dieu hoa",
        "gan ",
    )
    return any(cue in lowered for cue in filter_cues)


def should_query_full_db(user_text: str, intent: str) -> bool:
    """District/filter listing questions should hit Postgres, not only the UI page."""
    if intent == "general":
        return False
    if is_page_scoped_request(user_text):
        return False
    if intent == "search":
        return True
    if intent in {"compare_results", "advise", "listing_detail"}:
        return has_location_or_filter_cues(user_text)
    return False


def merge_match_filters(base: MatchFilters | None, new: MatchFilters) -> MatchFilters:
    if base is None:
        return new
    data = base.model_dump()
    for key, val in new.model_dump().items():
        if val is None:
            continue
        if isinstance(val, list) and not val:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        data[key] = val
    return MatchFilters(**data)


def match_result_to_card(result: MatchResult) -> ListingCard:
    return ListingCard(
        source_id=result.source_id,
        title=result.title,
        district=result.district,
        address_text=result.address_text,
        price_vnd=result.price_vnd,
        area_min_m2=result.area_min_m2,
        area_max_m2=result.area_max_m2,
        room_layout_tags=list(result.room_layout_tags),
        amenities=list(result.amenities),
        common_amenities=list(result.common_amenities),
        service_fees_summary=format_service_fee_summary(result.service_fees),
        contact_phone=result.contact_phone,
        source_url=result.source_url,
        source_platform=platform_from_source_id(result.source_id),
        short_description=result.short_description,
        thumbnail_url=None,
    )


def resolve_source_id(
    *,
    explicit_id: str | None,
    result_index: int | None,
    last_result_ids: list[str],
    focused_source_id: str | None,
    user_text: str,
) -> str | None:
    if explicit_id:
        return explicit_id
    if focused_source_id:
        return focused_source_id
    if result_index is not None and 1 <= result_index <= len(last_result_ids):
        return last_result_ids[result_index - 1]

    lowered = user_text.lower()
    index_match = re.search(
        r"(?:tin|căn|phòng|kết quả|số)\s*(?:thứ\s*)?(\d+)",
        lowered,
    )
    if index_match:
        idx = int(index_match.group(1))
        if 1 <= idx <= len(last_result_ids):
            return last_result_ids[idx - 1]

    for source_id in last_result_ids:
        detail = get_listing_by_source_id(source_id)
        if detail and detail.title and detail.title.lower() in lowered:
            return source_id
    return None


def format_page_context_for_prompt(page_context: SearchPageContext | None) -> str:
    if page_context is None or not page_context.visible_listings:
        return "No listings visible on search page."
    lines = [
        f"Search page (UI only — NOT the full database): {page_context.total} total, page {page_context.page}",
        f"Filters: {page_context.filters_summary or 'none'}",
        f"Visible on this page ({len(page_context.visible_listings)} of {page_context.total}):",
    ]
    for i, card in enumerate(page_context.visible_listings, start=1):
        lines.append(
            f"  {i}. {card.source_id} | {card.title} | {card.district} | "
            f"price={card.price_vnd} | area={card.area_min_m2}-{card.area_max_m2} | "
            f"amenities={card.amenities} | fees={'; '.join(card.service_fees_summary)}"
        )
    return "\n".join(lines)


def format_listing_detail_lines(detail: ListingDetail, index: int) -> list[str]:
    desc = (detail.description_long or detail.short_description or "")[:600]
    return [
        f"--- Listing {index}: {detail.source_id} ---",
        f"Title: {detail.title}",
        f"District: {detail.district} | Address: {detail.address_text}",
        f"Price: {detail.price_vnd} | Area: {detail.area_min_m2}-{detail.area_max_m2} m²",
        f"Room amenities: {detail.amenities}",
        f"Building amenities: {detail.common_amenities}",
        f"Service fees: {'; '.join(detail.service_fees_summary)}",
        f"Near: {', '.join(detail.near_landmarks) if detail.near_landmarks else '—'}",
        f"Building: {detail.building}",
        f"Phone: {detail.contact_phone}",
        f"Description: {desc}",
    ]


def load_listings_for_comparison(
    page_context: SearchPageContext | None,
    last_result_ids: list[str],
    user_text: str = "",
) -> tuple[list[ListingDetail], list[ListingCard]]:
    page_scoped = is_page_scoped_request(user_text)
    source_ids: list[str] = []
    cards: list[ListingCard] = []

    if page_scoped and page_context and page_context.visible_listings:
        for card in page_context.visible_listings:
            source_ids.append(card.source_id)
            cards.append(card)
    elif last_result_ids:
        source_ids = list(last_result_ids)
    elif page_context and page_context.visible_listings:
        for card in page_context.visible_listings:
            source_ids.append(card.source_id)
            cards.append(card)

    details: list[ListingDetail] = []
    for source_id in source_ids:
        detail = get_listing_by_source_id(source_id)
        if detail is not None:
            details.append(detail)
            if not cards:
                cards.append(ListingCard.model_validate(detail.model_dump()))
    return details, cards


def resolve_listing_result_ids(
    client_last_result_ids: list[str],
    page_context: SearchPageContext | None,
    user_text: str = "",
) -> list[str]:
    """Prefer DB search results over the current UI page unless user is page-scoped."""
    if is_page_scoped_request(user_text):
        if page_context and page_context.visible_listings:
            return [c.source_id for c in page_context.visible_listings]
    if client_last_result_ids:
        return list(client_last_result_ids)
    if page_context and page_context.visible_listings:
        return [c.source_id for c in page_context.visible_listings]
    return []


def format_messages_for_prompt(messages: list[dict[str, str]], limit: int = 12) -> str:
    recent = messages[-limit:]
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def listing_ids_from_page(page_context: SearchPageContext | None) -> list[str]:
    if not page_context or not page_context.visible_listings:
        return []
    return [c.source_id for c in page_context.visible_listings]


def is_follow_up_advise(messages: list[dict[str, str]]) -> bool:
    """Heuristic: user refined preferences after an earlier turn."""
    if len(messages) < 2:
        return False
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user = (msg.get("content") or "").lower()
            break
    follow_markers = (
        "sinh viên",
        "2 người",
        "hai người",
        "tr/người",
        "triệu/người",
        "tr5",
        "2tr",
        "3tr",
        "ngân sách",
        "tài chính",
        "budget",
        "nên chọn",
        "chọn căn",
        "chọn phòng",
        "phù hợp",
        "đủ rộng",
        "học tại",
        "bao gồm",
        "dịch vụ",
        "điện nước",
        "câu hỏi",
        "trả lời",
    )
    return any(m in last_user for m in follow_markers)


def format_compact_listings(details: list[ListingDetail]) -> str:
    lines = []
    for i, d in enumerate(details, start=1):
        fees = "; ".join(d.service_fees_summary) if d.service_fees_summary else "—"
        lines.append(
            f"{i}. {d.title} | {d.price_vnd} VND/tháng | "
            f"{d.area_min_m2 or '?'}m² | amenities={d.amenities} | fees={fees}"
        )
    return "\n".join(lines)


def format_user_preferences(prefs: dict) -> str:
    if not prefs:
        return "Chưa có thông tin sở thích người dùng."
    parts = []
    for key, val in prefs.items():
        if val is not None and val != "" and val != []:
            parts.append(f"- {key}: {val}")
    return "\n".join(parts) if parts else "Chưa có thông tin sở thích người dùng."
