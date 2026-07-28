"""Vietnamese text helpers and Hanoi district normalization."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# Canonical Hanoi district names (slug → display name with diacritics)
HANOI_DISTRICT_SLUGS: dict[str, str] = {
    "ba-dinh": "Ba Đình",
    "hoan-kiem": "Hoàn Kiếm",
    "tay-ho": "Tây Hồ",
    "long-bien": "Long Biên",
    "cau-giay": "Cầu Giấy",
    "dong-da": "Đống Đa",
    "hai-ba-trung": "Hai Bà Trưng",
    "hoang-mai": "Hoàng Mai",
    "thanh-xuan": "Thanh Xuân",
    "nam-tu-liem": "Nam Từ Liêm",
    "bac-tu-liem": "Bắc Từ Liêm",
    "ha-dong": "Hà Đông",
    "son-tay": "Sơn Tây",
    "me-tri": "Mễ Trì",
}

# Fuzzy aliases LLM often produces → canonical
DISTRICT_ALIASES: dict[str, str] = {
    "cau giay": "Cầu Giấy",
    "cáu giáy": "Cầu Giấy",
    "cau giấy": "Cầu Giấy",
    "nam tu liem": "Nam Từ Liêm",
    "nam từ liem": "Nam Từ Liêm",
    "nam từ liên": "Nam Từ Liêm",
    "nam đơu liên": "Nam Từ Liêm",
    "nam tu liên": "Nam Từ Liêm",
    "dong da": "Đống Đa",
    "đống đa": "Đống Đa",
    "quận cầu giấy": "Cầu Giấy",
    "quận nam từ liêm": "Nam Từ Liêm",
}


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


def _fold_key(text: str) -> str:
    text = normalize_unicode(text).lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def normalize_district(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = normalize_unicode(name)
    cleaned = re.sub(r"^quận\s+", "", cleaned, flags=re.I).strip()
    alias = DISTRICT_ALIASES.get(_fold_key(cleaned))
    if alias:
        return alias
    for slug, canonical in HANOI_DISTRICT_SLUGS.items():
        if _fold_key(canonical) == _fold_key(cleaned):
            return canonical
    return cleaned


ALLOWED_AMENITIES = frozenset({"may_giat", "bep", "dieu_hoa", "nong_lanh", "ban_cong"})

AMENITY_ALIASES: dict[str, str] = {
    "be_p": "bep",
    "be": "bep",
    "bếp": "bep",
    "may_giat": "may_giat",
    "máy_giặt": "may_giat",
    "dieu_hoa": "dieu_hoa",
    "điều_hòa": "dieu_hoa",
    "nong_lanh": "nong_lanh",
    "nóng_lạnh": "nong_lanh",
    "ban_cong": "ban_cong",
    "ban_công": "ban_cong",
}


def normalize_amenities(items: list[str] | None) -> list[str]:
    if not items:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _fold_key(str(item)).replace(" ", "_")
        key = AMENITY_ALIASES.get(key, key)
        if key in ALLOWED_AMENITIES and key not in seen:
            normalized.append(key)
            seen.add(key)
    return normalized


def district_from_phongtot_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.lower()
    match = re.search(r"/quan-([a-z0-9-]+)/", path)
    if not match:
        return None
    slug = match.group(1)
    if slug in HANOI_DISTRICT_SLUGS:
        return HANOI_DISTRICT_SLUGS[slug]
    # quan-cau-giay → cau-giay
    if slug.startswith("quan-"):
        slug = slug.removeprefix("quan-")
    return HANOI_DISTRICT_SLUGS.get(slug)


def district_from_nhatot_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.lower()
    match = re.search(r"/thue-phong-tro-quan-([a-z0-9-]+)-ha-noi/", path)
    if not match:
        return None
    slug = match.group(1)
    return HANOI_DISTRICT_SLUGS.get(slug)


def district_from_address(address: str | None) -> str | None:
    if not address:
        return None
    match = re.search(r"Quận\s+([^,]+)", address, re.I)
    if match:
        return normalize_district(match.group(1).strip())
    return None
