from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class CrawlItem:
    source_id: str
    body: str
    source_url: str
    source_platform: str
    crawled_at: datetime


class CrawlSource(ABC):
    """Adapter for a single crawl provider (Firecrawl, HTTP fetch, …)."""

    adapter: str

    @abstractmethod
    def fetch_items(self, urls: list[str]) -> list[CrawlItem]:
        """Fetch page content for each URL. Raises on fatal config errors only."""


def platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host in {"phongtot.com", "www.phongtot.com"}:
        return "phongtot"
    if host in {"nhatot.com", "www.nhatot.com", "chotot.com", "www.chotot.com"}:
        return "nhatot"
    return "web"


def is_phongtot_url(url: str) -> bool:
    return platform_from_url(url) == "phongtot"


def source_id_from_url(url: str, platform: str | None = None) -> str:
    site = platform or platform_from_url(url)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{site}_{digest}"


def load_urls_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"URL list not found: {path}")

    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # First token only — ignore accidental title text after URL
        token = stripped.split()[0]
        if token.startswith("http"):
            urls.append(token)
    return urls
