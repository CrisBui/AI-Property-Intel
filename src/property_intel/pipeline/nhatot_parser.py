"""Parse structured fields from NhaTot / Chợ Tốt listing page markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from property_intel.pipeline.vietnamese_utils import (
    district_from_address,
    district_from_nhatot_url,
    normalize_district,
    normalize_unicode,
)

_PHONE_RE = re.compile(
    r"(?:SĐT\s*Liên\s*hệ|Hiện\s*số)\*?\*?\s*:?\s*((?:\+84|0)[\d\s*]{6,12})",
    re.I,
)
_PRICE_LINE_RE = re.compile(
    r"\*\*([\d.,]+)\s*triệu/tháng\*\*",
    re.I,
)
_AREA_LINE_RE = re.compile(
    r"\*\*([\d.,]+)\s*m\s*²\*\*",
    re.I,
)
_ELECTRICITY_RE = re.compile(
    r"Điện\s+([\d.,]+)\s*k(?:/|\s*/\s*)s(?:ố|o)\b",
    re.I,
)
_WATER_M3_RE = re.compile(
    r"Nước\s+([\d.,]+)\s*k(?:/|\s*/\s*)m3\b",
    re.I,
)
_WATER_M3_UNICODE_RE = re.compile(
    r"Nước\s+([\d.,]+)\s*k(?:/|\s*/\s*)m³\b",
    re.I,
)
_WATER_PERSON_RE = re.compile(
    r"Nước\s+Coway\s+([\d.,]+)\s*k(?:/|\s*/\s*)ng(?:ười|uoi)\b",
    re.I,
)
_WATER_PERSON_GENERIC_RE = re.compile(
    r"(?<!Coway\s)Nước\s+([\d.,]+)\s*k(?:/|\s*/\s*)ng(?:ười|uoi)\b",
    re.I,
)
_WIFI_RE = re.compile(
    r"(?:Wifi|Internet)\s+([\d.,]+)\s*k(?:/|\s*/\s*)ph(?:òng|ong)\b",
    re.I,
)
_SERVICE_OTHER_RE = re.compile(
    r"DVC\s+([\d.,]+)\s*k(?:/|\s*/\s*)ng(?:ười|uoi)\b",
    re.I,
)


@dataclass
class NhaTotParsed:
    title: str | None = None
    address_text: str | None = None
    district: str | None = None
    price_vnd_min: int | None = None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    service_fees: dict[str, int | str | None] = field(default_factory=dict)
    contact_phone: str | None = None
    description_long: str | None = None
    furnishing: str | None = None
    deposit_vnd: int | None = None


def extract_nhatot_main_content(body: str) -> str:
    """Keep listing content from the main H1 heading onward."""
    text = normalize_unicode(body)
    match = re.search(r"^#\s+.+\S", text, re.M)
    if match:
        return text[match.start() :].strip()
    return text


def _parse_vnd_from_triệu(raw: str | None) -> int | None:
    if not raw:
        return None
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    try:
        return int(float(cleaned) * 1_000_000)
    except ValueError:
        return None


def _parse_k_amount(raw: str | None) -> int | None:
    """Parse '4.2k' or '35k' style amounts to VND."""
    if not raw:
        return None
    cleaned = raw.strip().replace(",", ".")
    try:
        return int(float(cleaned) * 1_000)
    except ValueError:
        return None


def _parse_vnd_amount(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    return int(digits)


def _parse_service_fees(text: str) -> dict[str, int | str | None]:
    fees: dict[str, int | str | None] = {
        "electricity_vnd_per_kwh": None,
        "water_unit": None,
        "water_vnd_per_m3": None,
        "water_vnd_per_person": None,
        "internet_vnd_per_room": None,
        "other_vnd_per_person": None,
        "water_raw": None,
    }
    elec = _ELECTRICITY_RE.search(text)
    if elec:
        fees["electricity_vnd_per_kwh"] = _parse_k_amount(elec.group(1))

    water_m3 = _WATER_M3_UNICODE_RE.search(text) or _WATER_M3_RE.search(text)
    if water_m3:
        fees["water_unit"] = "per_m3"
        fees["water_vnd_per_m3"] = _parse_k_amount(water_m3.group(1)) or _parse_vnd_amount(
            water_m3.group(1)
        )
        fees["water_raw"] = f"{water_m3.group(1).strip()}k/m³"

    water_person = _WATER_PERSON_GENERIC_RE.search(text) or _WATER_PERSON_RE.search(text)
    if water_person and fees["water_unit"] is None:
        fees["water_unit"] = "per_person"
        fees["water_vnd_per_person"] = _parse_k_amount(water_person.group(1))
        fees["water_raw"] = f"{water_person.group(1).strip()}k/người"

    wifi = _WIFI_RE.search(text)
    if wifi:
        fees["internet_vnd_per_room"] = _parse_k_amount(wifi.group(1))

    dvc = _SERVICE_OTHER_RE.search(text)
    if dvc:
        fees["other_vnd_per_person"] = _parse_k_amount(dvc.group(1))

    return fees


def _parse_description_long(text: str) -> str | None:
    match = re.search(
        r"Mô tả chi tiết\s*\n+(.*?)(?:\n(?:SĐT Liên hệ|Hiện số|\*\*SĐT|Chat\b|Tin tương tự|Báo tin))",
        text,
        re.S | re.I,
    )
    if not match:
        return None
    chunk = re.sub(r"\n{3,}", "\n\n", match.group(1).strip())
    return chunk[:8000] if chunk else None


def parse_nhatot_body(body: str, source_url: str | None = None) -> NhaTotParsed:
    full_text = normalize_unicode(body)
    text = extract_nhatot_main_content(full_text)
    parsed = NhaTotParsed()

    title_match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    if title_match:
        parsed.title = normalize_unicode(title_match.group(1))

    price_match = _PRICE_LINE_RE.search(text)
    if price_match:
        parsed.price_vnd_min = _parse_vnd_from_triệu(price_match.group(1))

    area_match = _AREA_LINE_RE.search(text)
    if area_match:
        area_val = float(area_match.group(1).replace(",", "."))
        parsed.area_min_m2 = area_val
        parsed.area_max_m2 = area_val

    addr_match = re.search(
        r"Địa chỉ bất động sản\s*\n+([^\n]+)",
        text,
        re.I,
    )
    if addr_match:
        addr = addr_match.group(1).strip()
        addr = re.sub(r"\([^)]*\)\s*$", "", addr).strip()
        parsed.address_text = normalize_unicode(addr)

    parsed.district = (
        district_from_nhatot_url(source_url)
        or district_from_address(parsed.address_text)
        or normalize_district(
            parsed.title.split("-")[-1].strip() if parsed.title and "-" in parsed.title else None
        )
    )

    furnish_match = re.search(
        r"Tình trạng nội thất\s*\n+\s*\*\*(.+?)\*\*",
        text,
        re.I,
    )
    if furnish_match:
        parsed.furnishing = normalize_unicode(furnish_match.group(1))

    deposit_match = re.search(
        r"Số tiền cọc\s*\n+\s*\*\*([\d.,]+)\s*đ/tháng\*\*",
        text,
        re.I,
    )
    if deposit_match:
        parsed.deposit_vnd = _parse_vnd_amount(deposit_match.group(1))

    parsed.service_fees = _parse_service_fees(full_text)
    parsed.description_long = _parse_description_long(text)

    phone_match = _PHONE_RE.search(text)
    if not phone_match:
        phone_match = _PHONE_RE.search(full_text)
    if phone_match:
        parsed.contact_phone = re.sub(r"\s+", "", phone_match.group(1))

    return parsed
