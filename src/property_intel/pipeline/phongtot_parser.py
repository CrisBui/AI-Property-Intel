"""Parse structured fields from PhongTot listing page markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from property_intel.pipeline.vietnamese_utils import (
    district_from_address,
    district_from_phongtot_url,
    normalize_district,
    normalize_unicode,
)

_PRICE_RE = re.compile(r"([\d.,]+)\s*(?:đ|vnd|vnđ)", re.I)
_PHONE_RE = re.compile(
    r"(?:\+84|0)(?:\s*\d){8,10}",
    re.I,
)


@dataclass
class PhongTotParsed:
    title: str | None = None
    address_text: str | None = None
    district: str | None = None
    price_vnd_min: int | None = None
    floor_count: int | None = None
    room_count: int | None = None
    renovation_year: int | None = None
    service_fees: dict[str, int | str | None] = field(default_factory=dict)
    common_amenities: list[str] = field(default_factory=list)
    contact_phone: str | None = None
    description_long: str | None = None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    price_note: str | None = None


def extract_phongtot_main_content(body: str) -> str:
    """Keep listing content from the main H1 heading onward."""
    text = normalize_unicode(body)
    match = re.search(r"^#\s+.+\S", text, re.M)
    if match:
        return text[match.start() :].strip()
    return text


def _parse_vnd_amount(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    return int(digits)


def _parse_label_int(text: str, label: str) -> int | None:
    pattern = rf"{re.escape(label)}\s*\n+\s*(\d+)"
    match = re.search(pattern, text, re.I)
    if match:
        return int(match.group(1))
    return None


def _parse_water_fee(text: str) -> dict[str, int | str | None]:
    result: dict[str, int | str | None] = {
        "water_unit": None,
        "water_vnd_per_m3": None,
        "water_vnd_per_person": None,
        "water_raw": None,
    }
    match = re.search(
        r"Tiền nước\s*\n+\s*([\d.,]+)\s*đ\s*/\s*(m3|m³|người|nguoi)\b",
        text,
        re.I,
    )
    if match:
        amount = _parse_vnd_amount(match.group(1))
        unit_token = match.group(2).lower().replace("³", "3")
        raw_suffix = "đ/m³" if unit_token == "m3" else "đ/người"
        result["water_raw"] = f"{match.group(1).strip()} {raw_suffix}"
        if unit_token == "m3":
            result["water_unit"] = "per_m3"
            result["water_vnd_per_m3"] = amount
        else:
            result["water_unit"] = "per_person"
            result["water_vnd_per_person"] = amount
        return result

    raw_line = re.search(r"Tiền nước\s*\n+\s*(.+?)(?:\n|$)", text, re.I)
    if raw_line:
        line = raw_line.group(1).strip()
        if re.search(r"miễn|free|included|bao gồm", line, re.I):
            result["water_unit"] = "included"
        else:
            result["water_unit"] = "unknown"
        result["water_raw"] = line
    return result


def _parse_service_fees(text: str) -> dict[str, int | str | None]:
    fees: dict[str, int | str | None] = dict(_parse_water_fee(text))
    patterns: dict[str, str] = {
        "electricity_vnd_per_kwh": r"Tiền điện\s*\n+\s*([\d.,]+)\s*đ/kWh",
        "internet_vnd_per_room": r"Internet\s*\n+\s*([\d.,]+)\s*đ/phòng",
        "laundry_vnd_per_person": r"Giặt sấy\s*\n+\s*([\d.,]+)\s*đ/người",
        "other_vnd_per_person": r"Dịch vụ khác\s*\n+\s*([\d.,]+)\s*đ/người",
        "sanitation_vnd_per_person": r"Vệ sinh\s*\n+\s*([\d.,]+)\s*đ/người",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        fees[key] = _parse_vnd_amount(match.group(1)) if match else None
    return fees


def _parse_common_amenities(text: str) -> list[str]:
    block_match = re.search(
        r"Tiện ích chung\s*\n(.*?)(?:Phí dịch vụ chung|Thu gọn|$)",
        text,
        re.S | re.I,
    )
    if not block_match:
        return []
    block = block_match.group(1)
    amenities: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("/imgs/"):
            continue
        if stripped.lower() in {"điểm nổi bật", "tiện ích chung"}:
            continue
        amenities.append(stripped)
    return amenities


def _parse_description_long(text: str) -> str | None:
    """Marketing description between building stats and 'Thu gọn' / amenities."""
    start = re.search(r"Năm cải tạo\s*\n+\s*\d*", text, re.I)
    end = re.search(r"(Thu gọn|Điểm nổi bật|Tiện ích chung)", text, re.I)
    if not start:
        return None
    chunk = text[start.end() : end.start() if end else len(text)].strip()
    chunk = re.sub(r"\n{3,}", "\n\n", chunk)
    return chunk[:8000] if chunk else None


def parse_phongtot_body(body: str, source_url: str | None = None) -> PhongTotParsed:
    full_text = normalize_unicode(body)
    text = extract_phongtot_main_content(full_text)
    parsed = PhongTotParsed()

    title_match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    if title_match:
        parsed.title = normalize_unicode(title_match.group(1))

    addr_match = re.search(
        r"^((?:Đường|Phố|Ngõ|Số|Khu).+Hà Nội)\s*$",
        text,
        re.M | re.I,
    )
    if addr_match:
        parsed.address_text = normalize_unicode(addr_match.group(1))

    parsed.district = (
        district_from_phongtot_url(source_url)
        or district_from_address(parsed.address_text)
        or normalize_district(
            parsed.title.split("-")[-1].strip() if parsed.title and "-" in parsed.title else None
        )
    )

    price_match = re.search(r"Giá phòng từ\s*\n+\s*([\d.,]+)", full_text, re.I)
    if not price_match:
        price_match = re.search(r"Giá thuê chỉ từ:?\s*\n?\s*([\d.,]+)", full_text, re.I)
    if not price_match:
        price_match = re.search(
            r"([\d]{1,3}(?:\.\d{3})+)\s*(?:đ|vnd)",
            full_text,
            re.I,
        )
    if price_match:
        parsed.price_vnd_min = _parse_vnd_amount(price_match.group(1))

    parsed.floor_count = _parse_label_int(text, "Số tầng")
    parsed.room_count = _parse_label_int(text, "Số phòng")
    year_match = re.search(r"Năm cải tạo\s*\n+\s*(\d{4})", text, re.I)
    if year_match:
        parsed.renovation_year = int(year_match.group(1))

    parsed.service_fees = _parse_service_fees(full_text)
    parsed.common_amenities = _parse_common_amenities(full_text)
    parsed.description_long = _parse_description_long(text)

    phone_match = _PHONE_RE.search(text)
    if not phone_match:
        phone_match = _PHONE_RE.search(full_text)
    if phone_match:
        parsed.contact_phone = re.sub(r"\s+", "", phone_match.group(0))

    area_match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*m\s*2", full_text, re.I)
    if area_match:
        parsed.area_min_m2 = float(area_match.group(1))
        parsed.area_max_m2 = float(area_match.group(2))
    else:
        single_area = re.search(r"(\d+(?:[.,]\d+)?)\s*m\s*2", full_text, re.I)
        if single_area:
            val = float(single_area.group(1).replace(",", "."))
            parsed.area_min_m2 = val
            parsed.area_max_m2 = val

    if re.search(r"Giá phòng từ|Giá thuê chỉ từ", full_text, re.I):
        parsed.price_note = "Giá phòng từ (chưa bao gồm phí dịch vụ)"

    return parsed
