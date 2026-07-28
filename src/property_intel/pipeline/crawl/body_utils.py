"""Normalize and truncate crawled page text for LLM extract."""

from __future__ import annotations

import re

_NOISE_LINE_RE = re.compile(
    r"^(\s*[-*]\s*)?(menu|đăng nhập|đăng ký|cookie|quảng cáo|"
    r"chính sách|footer|header|breadcrumb)\b",
    re.IGNORECASE,
)

_PHONGTOT_NAV_LINE_RE = re.compile(
    r"^(\s*[-*]\s*)?(hồ chí minh|"
    r"cho thuê phòng trọ quận\s+\d+|"
    r"cho thuê phòng trọ hà nội|"
    r"phòng tốt)\b",
    re.IGNORECASE,
)

_PHONGTOT_CATEGORY_URL_RE = re.compile(
    r"phongtot\.com/cho-thue-phong-tro-(?:hn|hcm)/quan-[^/\s\"']+/?(?:\s|$|\"|\))",
    re.IGNORECASE,
)

_NHATOT_NAV_LINE_RE = re.compile(
    r"^(\s*[-*\d.]+\s*)?(?:nhà tốt|thuê phòng trọ|chia sẻ qua|báo cáo tin đăng|"
    r"cần trợ giúp\?|lưu$|tin tương tự|tin liên quan|đăng nhanh)\b",
    re.IGNORECASE,
)

_NHATOT_NOISE_LINE_RE = re.compile(
    r"^(?:!\[|!\[\[|1\s*/\s*\d+|static\.chotot\.com|cdn\.chotot\.com/videodelivery)",
    re.IGNORECASE,
)


def _strip_nhatot_nav(body: str) -> str:
    """Drop breadcrumbs, gallery chrome, and similar-listing blocks on NhaTot pages."""
    kept: list[str] = []
    stop = False
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "" and not stop:
                kept.append("")
            continue
        if re.search(r"^tin tương tự|^tin liên quan|^báo tin không hợp lệ", stripped, re.I):
            stop = True
        if stop:
            continue
        if _NHATOT_NAV_LINE_RE.match(stripped):
            continue
        if _NHATOT_NOISE_LINE_RE.match(stripped):
            continue
        if re.match(r"^\d+\.\s*\[", stripped):
            continue
        kept.append(stripped)
    return "\n".join(kept).strip()


def _strip_phongtot_nav(body: str) -> str:
    """Drop sidebar/category links common on PhongTot detail pages."""
    kept: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if _PHONGTOT_NAV_LINE_RE.match(stripped):
            continue
        if _PHONGTOT_CATEGORY_URL_RE.search(stripped) and "-tn" not in stripped.lower():
            continue
        kept.append(stripped)
    return "\n".join(kept).strip()


def clean_crawl_body(body: str, source_platform: str | None = None) -> str:
    """Strip markdown noise common on listing/search pages."""
    text = body.replace("\r\n", "\n").strip()
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if source_platform == "phongtot":
        text = _strip_phongtot_nav(text)
    elif source_platform == "nhatot":
        text = _strip_nhatot_nav(text)

    kept: list[str] = []
    seen_lines: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if _NOISE_LINE_RE.match(stripped):
            continue
        key = stripped.lower()
        if key in seen_lines:
            continue
        seen_lines.add(key)
        kept.append(stripped)

    cleaned = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def truncate_body(body: str, max_chars: int) -> str:
    if len(body) <= max_chars:
        return body
    return body[:max_chars].rstrip() + "\n\n[... truncated ...]"


def prepare_body_for_storage(body: str, max_chars: int, source_platform: str | None = None) -> str:
    return truncate_body(clean_crawl_body(body, source_platform=source_platform), max_chars)


def prepare_body_for_llm(body: str, max_chars: int, source_platform: str | None = None) -> str:
    cleaned = clean_crawl_body(body, source_platform=source_platform)
    return truncate_body(cleaned, max_chars)
