import logging
from collections import Counter, defaultdict

from sqlalchemy import select

from property_intel.db.json_utils import as_json_list
from property_intel.db.models import ListingRow
from property_intel.db.session import session_scope
from property_intel.models.market import AmenityStat, AreaMarketStats, MarketReport

logger = logging.getLogger(__name__)


def _normalize_area_key(key: str) -> str:
    return key.lower().strip().replace(" ", "_")


def _primary_area(row: ListingRow) -> str:
    landmarks = as_json_list(row.near_landmarks_json)
    if landmarks:
        return _normalize_area_key(landmarks[0])
    if row.district:
        return _normalize_area_key(row.district)
    return "unknown"


def _row_matches_landmark(row: ListingRow, landmark: str) -> bool:
    landmarks = as_json_list(row.near_landmarks_json)
    text_blob = " ".join(
        [
            row.title or "",
            row.description_raw or "",
            row.address_text or "",
            row.district or "",
            " ".join(landmarks),
        ]
    ).lower()
    landmark_norm = landmark.lower().replace("_", " ")
    return (
        landmark.lower() in landmarks
        or landmark_norm in text_blob
        or landmark.lower() in text_blob
    )


def compute_market_report(landmark: str | None = None) -> MarketReport:
    with session_scope() as session:
        rows = session.scalars(select(ListingRow).order_by(ListingRow.source_id)).all()
        session.expunge_all()

    if landmark:
        rows = [row for row in rows if _row_matches_landmark(row, landmark)]

    grouped: dict[str, list[ListingRow]] = defaultdict(list)
    for row in rows:
        grouped[_primary_area(row)].append(row)

    areas: list[AreaMarketStats] = []
    for area_key in sorted(grouped.keys()):
        area_rows = grouped[area_key]
        prices = [row.price_vnd for row in area_rows if row.price_vnd is not None]

        amenity_counter: Counter[str] = Counter()
        for row in area_rows:
            for amenity in as_json_list(row.amenities_json):
                amenity_counter[amenity] += 1

        total = len(area_rows)
        top_amenities = [
            AmenityStat(
                amenity=name,
                count=count,
                pct=round(count / total * 100, 1) if total else 0.0,
            )
            for name, count in amenity_counter.most_common(5)
        ]

        areas.append(
            AreaMarketStats(
                area_key=area_key,
                listing_count=total,
                priced_count=len(prices),
                price_min_vnd=min(prices) if prices else None,
                price_max_vnd=max(prices) if prices else None,
                price_avg_vnd=int(sum(prices) / len(prices)) if prices else None,
                top_amenities=top_amenities,
            )
        )

    logger.info(
        "Market report: total=%d areas=%d filter=%s",
        len(rows),
        len(areas),
        landmark,
    )
    return MarketReport(
        total_listings=len(rows),
        areas=areas,
        filter_landmark=landmark,
    )


def format_market_report(report: MarketReport) -> str:
    lines: list[str] = []
    title = "BÁO CÁO THỊ TRƯỜNG (từ listings đã extract)"
    if report.filter_landmark:
        title += f" — lọc landmark: {report.filter_landmark.replace('_', ' ')}"
    lines.append(title)
    lines.append(f"Tổng listings: {report.total_listings}")
    lines.append("")

    if not report.areas:
        lines.append("Không có dữ liệu.")
        return "\n".join(lines)

    for area in report.areas:
        lines.append(f"## Khu: {area.area_key.replace('_', ' ')}")
        lines.append(f"   Số tin: {area.listing_count} (có giá: {area.priced_count})")
        if area.price_avg_vnd is not None:
            lines.append(
                f"   Giá: min {area.price_min_vnd:,} — avg {area.price_avg_vnd:,} "
                f"— max {area.price_max_vnd:,} VND/tháng"
            )
        else:
            lines.append("   Giá: không đủ dữ liệu giá rõ")
        if area.top_amenities:
            amenity_text = ", ".join(
                f"{a.amenity} ({a.count}, {a.pct}%)" for a in area.top_amenities
            )
            lines.append(f"   Tiện ích phổ biến: {amenity_text}")
        lines.append("")

    lines.append(
        "Lưu ý: số liệu chỉ từ seed data hiện có, không phải thống kê thị trường thật."
    )
    return "\n".join(lines)
