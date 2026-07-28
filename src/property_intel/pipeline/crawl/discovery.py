"""Discover listing detail URLs from search/category pages."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from property_intel.config import get_settings
from property_intel.pipeline.crawl.base import load_urls_file
from property_intel.pipeline.crawl.sources import FirecrawlSource

logger = logging.getLogger(__name__)

# NhaTot / Chợ Tốt: .../133355891.htm
NHATOT_LISTING_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:nhatot|chotot)\.com/(?!.*/q-)[^\s)\]\"'<>]+?\d{6,}\.htm",
    re.IGNORECASE,
)

# PhongTot: .../quan-dong-da/building-slug-tn935
PHONGTOT_LISTING_URL_RE = re.compile(
    r"https?://(?:www\.)?phongtot\.com/cho-thue-phong-tro-[^/\s\"']+/[^/\s\"']+/[^/\s\"'?#]+-tn\d+",
    re.IGNORECASE,
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)]+)\)")


def _normalize_nhatot_url(url: str) -> str:
    cleaned = url.split("#")[0].split("?")[0].strip()
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if host not in {"www.nhatot.com", "nhatot.com", "www.chotot.com", "chotot.com"}:
        return ""
    path = parsed.path.rstrip("/")
    if not path.endswith(".htm") or "/q-" in path.lower():
        return ""
    if not re.search(r"/\d{6,}\.htm$", path, re.I):
        return ""
    return f"https://{parsed.netloc}{path}"


def _normalize_phongtot_url(url: str) -> str:
    cleaned = url.split("#")[0].split("?")[0].strip()
    if not PHONGTOT_LISTING_URL_RE.match(cleaned):
        return ""
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if host not in {"www.phongtot.com", "phongtot.com"}:
        return ""
    return f"https://{parsed.netloc}{parsed.path.rstrip('/')}"


def normalize_listing_url(url: str) -> str:
    normalized = _normalize_nhatot_url(url)
    if normalized:
        return normalized
    return _normalize_phongtot_url(url)


def extract_listing_urls(content: str, page_links: list[str], base_url: str) -> list[str]:
    candidates: list[str] = []

    for link in page_links:
        normalized = normalize_listing_url(link)
        if normalized:
            candidates.append(normalized)

    for pattern in (NHATOT_LISTING_URL_RE, PHONGTOT_LISTING_URL_RE):
        for match in pattern.finditer(content):
            normalized = normalize_listing_url(match.group(0))
            if normalized:
                candidates.append(normalized)

    for match in MARKDOWN_LINK_RE.finditer(content):
        normalized = normalize_listing_url(match.group(1))
        if normalized:
            candidates.append(normalized)

    seen: set[str] = set()
    unique: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def discover_listing_urls(
    search_url: str, firecrawl: FirecrawlSource | None = None
) -> list[str]:
    scraper = firecrawl or FirecrawlSource()
    markdown, links = scraper.scrape_page(search_url)
    urls = extract_listing_urls(markdown, links, search_url)
    logger.info("Discovered %d listing URLs from %s", len(urls), search_url)
    return urls


def run_discover(
    search_urls_file: str | None = None,
    output_file: str | None = None,
    max_links_per_page: int = 30,
) -> dict[str, int]:
    settings = get_settings()
    input_path = (
        Path(search_urls_file).resolve()
        if search_urls_file
        else settings.crawl_search_urls_file_resolved
    )
    output_path = (
        Path(output_file).resolve()
        if output_file
        else settings.crawl_urls_file_resolved
    )

    search_urls = load_urls_file(input_path)
    if not search_urls:
        logger.warning("No search URLs in %s", input_path)
        return {"search_pages": 0, "discovered": 0, "written": 0, "output": str(output_path)}

    firecrawl = FirecrawlSource()
    discovered: list[str] = []
    seen: set[str] = set()

    for search_url in search_urls:
        try:
            page_urls = discover_listing_urls(search_url, firecrawl=firecrawl)[
                :max_links_per_page
            ]
            for url in page_urls:
                if url not in seen:
                    seen.add(url)
                    discovered.append(url)
        except Exception as exc:
            logger.exception("Discovery failed for %s: %s", search_url, exc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Auto-discovered listing URLs (PhongTot + NhaTot)",
        f"# Source search pages: {input_path.name}",
        "",
    ]
    lines.extend(discovered)
    output_path.write_text("\n".join(lines) + ("\n" if discovered else ""), encoding="utf-8")

    stats = {
        "search_pages": len(search_urls),
        "discovered": len(discovered),
        "written": len(discovered),
        "output": str(output_path),
    }
    logger.info(
        "Discovery complete: search_pages=%d discovered=%d output=%s",
        stats["search_pages"],
        stats["discovered"],
        output_path,
    )
    return stats
