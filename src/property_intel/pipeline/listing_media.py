"""Extract listing images and structure long descriptions for UI."""

from __future__ import annotations

import re

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
_CHOTOT_IMAGE_RE = re.compile(
    r"https?://cdn\.chotot\.com/[^\s)\]\"'<>]+?\.(?:jpg|jpeg|png|webp)(?:/[^\s)\]\"'<>]*)?",
    re.I,
)
_PHONGTOT_IMAGE_RE = re.compile(
    r"https?://(?:www\.)?phongtot\.com/imgs/[^\s)\]\"'<>]+",
    re.I,
)
_HTML_IMG_SRC_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)
_OG_IMAGE_RE = re.compile(
    r"""<meta[^>]+property=["']og:image(?::[^"']*)?["'][^>]+content=["']([^"']+)["']""",
    re.I,
)
_LINK_IMAGE_RE = re.compile(
    r"https?://[^\s)\]\"'<>]+(?:cdn\.chotot\.com|phongtot\.com/imgs)[^\s)\]\"'<>]*",
    re.I,
)
_SECTION_MARKERS = "📍🔹🎴•"
_LABELED_LINE_RE = re.compile(rf"^[{_SECTION_MARKERS}]\s*(.+?):\s*(.+)$")
_BULLET_LINE_RE = re.compile(r"^[-•]\s+(.+)$")
_EMOJI_NOTE_RE = re.compile(r"^[😳💡🔔]\s*(.+)$")
_INLINE_MARKER_RE = re.compile(
    rf"(?:^|[\s\\]+)([{_SECTION_MARKERS}])\s*([^:{_SECTION_MARKERS}\n]{{1,80}}?):\s*"
)


def extract_image_urls(body: str, source_platform: str | None = None) -> list[str]:
    """Collect listing photo URLs from crawled markdown/HTML."""
    if not body:
        return []

    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        cleaned = url.split("#")[0].split("?")[0].strip()
        if not cleaned or cleaned in seen:
            return
        lowered = cleaned.lower()
        if any(
            skip in lowered
            for skip in (
                "static.chotot.com",
                "chotot-icons",
                "/icons/",
                "thumbnail.gif",
                "videodelivery.net",
            )
        ):
            return
        seen.add(cleaned)
        urls.append(cleaned)

    for match in _MARKDOWN_IMAGE_RE.finditer(body):
        _add(match.group(1))
    for match in _HTML_IMG_SRC_RE.finditer(body):
        _add(match.group(1))
    for match in _OG_IMAGE_RE.finditer(body):
        _add(match.group(1))
    for pattern in (_CHOTOT_IMAGE_RE, _PHONGTOT_IMAGE_RE, _LINK_IMAGE_RE):
        for match in pattern.finditer(body):
            _add(match.group(0))

    return urls[:12]


def merge_crawl_images_into_body(
    body: str,
    *,
    html: str | None = None,
    links: list[str] | None = None,
    source_platform: str | None = None,
) -> str:
    """Append markdown image lines from Firecrawl html/links when markdown lacks photos."""
    existing = extract_image_urls(body, source_platform=source_platform)
    probe_parts = [body]
    if html:
        probe_parts.append(html)
    if links:
        probe_parts.extend(links)
    all_urls = extract_image_urls("\n".join(probe_parts), source_platform=source_platform)
    extra = [url for url in all_urls if url not in set(existing)][:12]
    if not extra:
        return body
    appendix = "\n\n" + "\n".join(f"![photo]({url})" for url in extra)
    return f"{body.rstrip()}{appendix}"


def parse_description_sections(text: str | None) -> list[dict[str, str | None]]:
    """Split NhaTot-style descriptions into labeled blocks (📍 Label: body)."""
    if not text or not text.strip():
        return []

    normalized = text.replace("\\\n", "\n").replace("\\", " ").strip()
    has_markers = any(marker in normalized for marker in ("📍", "🔹", "🎴"))
    if has_markers and normalized.count("\n") < 2:
        inline = _split_inline_marker_sections(normalized)
        if len(inline) > 1 or (inline and inline[0].get("label")):
            return inline

    sections: list[dict[str, str | None]] = []
    intro_parts: list[str] = []
    bullet_lines: list[str] = []

    def _flush_bullets() -> None:
        nonlocal bullet_lines
        if bullet_lines:
            sections.append(
                {
                    "label": "Chi tiết thêm",
                    "body": "\n".join(f"• {line}" for line in bullet_lines),
                }
            )
            bullet_lines = []

    def _flush_intro() -> None:
        nonlocal intro_parts
        if intro_parts:
            body = "\n".join(intro_parts).strip()
            if body:
                sections.append({"label": None, "body": body})
            intro_parts = []

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        labeled = _LABELED_LINE_RE.match(line)
        if labeled:
            _flush_intro()
            _flush_bullets()
            sections.append(
                {
                    "label": labeled.group(1).strip(),
                    "body": labeled.group(2).strip(),
                }
            )
            continue

        bullet = _BULLET_LINE_RE.match(line)
        if bullet:
            _flush_intro()
            bullet_lines.append(bullet.group(1).strip())
            continue

        note = _EMOJI_NOTE_RE.match(line)
        if note:
            _flush_intro()
            _flush_bullets()
            sections.append({"label": "Lưu ý", "body": note.group(1).strip()})
            continue

        if sections or bullet_lines:
            if sections:
                sections[-1]["body"] = (
                    f"{sections[-1]['body']}\n{line}".strip()
                    if sections[-1].get("body")
                    else line
                )
            else:
                bullet_lines.append(line)
        else:
            intro_parts.append(line)

    _flush_intro()
    _flush_bullets()

    if not sections and normalized:
        return [{"label": None, "body": normalized}]

    return sections


def _split_inline_marker_sections(text: str) -> list[dict[str, str | None]]:
    """Split a single-line or compact description on 📍/🔹 Label: markers."""
    matches = list(_INLINE_MARKER_RE.finditer(text))
    if not matches:
        return [{"label": None, "body": text.strip()}] if text.strip() else []

    sections: list[dict[str, str | None]] = []
    intro = text[: matches[0].start()].strip()
    if intro:
        sections.append({"label": None, "body": intro})

    for idx, match in enumerate(matches):
        label = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if label or body:
            sections.append({"label": label or None, "body": body})

    return sections
