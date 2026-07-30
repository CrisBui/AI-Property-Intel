from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from property_intel.config import get_settings
from property_intel.pipeline.crawl.base import (
    CrawlItem,
    CrawlSource,
    platform_from_url,
    source_id_from_url,
)
from property_intel.pipeline.crawl.body_utils import prepare_body_for_storage
from property_intel.pipeline.listing_media import merge_crawl_images_into_body

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; PropertyIntelBot/0.1; +https://github.com/local)"
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class UrlFetchSource(CrawlSource):
    """Simple HTTP GET + HTML-to-text (no JS rendering)."""

    adapter = "url_fetch"

    def fetch_items(self, urls: list[str]) -> list[CrawlItem]:
        items: list[CrawlItem] = []
        now = datetime.now(timezone.utc)

        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            for url in urls:
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" in content_type:
                        body = _html_to_text(response.text)
                    else:
                        body = response.text.strip()
                    if not body:
                        logger.warning("Empty body for %s", url)
                        continue
                    site = platform_from_url(url)
                    items.append(
                        CrawlItem(
                            source_id=source_id_from_url(url, site),
                            body=prepare_body_for_storage(
                                body,
                                max_chars=get_settings().crawl_max_body_chars,
                                source_platform=site,
                            ),
                            source_url=url,
                            source_platform=site,
                            crawled_at=now,
                        )
                    )
                except Exception as exc:
                    logger.exception("UrlFetch failed for %s: %s", url, exc)
        return items


class FirecrawlSource(CrawlSource):
    """Firecrawl /v1/scrape — handles JS-heavy pages."""

    adapter = "firecrawl"

    def __init__(self, api_key: str | None = None, api_base: str | None = None) -> None:
        settings = get_settings()
        self._api_key = (api_key or settings.firecrawl_api_key).strip()
        self._api_base = (api_base or settings.firecrawl_api_base).rstrip("/")
        self._max_body_chars = settings.crawl_max_body_chars
        if not self._api_key:
            raise ValueError(
                "FIRECRAWL_API_KEY is required for firecrawl source. Set it in .env"
            )

    def _scrape_payload(self, url: str) -> dict:
        site = platform_from_url(url)
        if site in {"phongtot", "nhatot"}:
            return {
                "url": url,
                "formats": ["markdown", "html", "links"],
                "onlyMainContent": True,
                "waitFor": 10000 if site == "nhatot" else 8000,
                "timeout": 90000,
            }
        return {
            "url": url,
            "formats": ["markdown", "html", "links"],
            "onlyMainContent": False,
            "waitFor": 5000,
        }

    def scrape_page(self, url: str) -> tuple[str, list[str], str]:
        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                f"{self._api_base}/v1/scrape",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=self._scrape_payload(url),
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"Firecrawl scrape failed for {url}: {payload}")
            data = payload.get("data") or {}
            body = (data.get("markdown") or data.get("content") or "").strip()
            html = (data.get("html") or "").strip()
            links = [str(link) for link in (data.get("links") or [])]
            if not body and not links and not html:
                raise RuntimeError(f"Empty Firecrawl response for {url}")
            return body, links, html

    def scrape_markdown(self, url: str) -> str:
        body, _links, _html = self.scrape_page(url)
        if not body:
            raise RuntimeError(f"Empty Firecrawl markdown for {url}")
        return body

    def fetch_items(self, urls: list[str]) -> list[CrawlItem]:
        items: list[CrawlItem] = []
        now = datetime.now(timezone.utc)

        for url in urls:
            try:
                site = platform_from_url(url)
                body, links, html = self.scrape_page(url)
                body = merge_crawl_images_into_body(
                    body,
                    html=html,
                    links=links,
                    source_platform=site,
                )
                body = prepare_body_for_storage(
                    body,
                    max_chars=self._max_body_chars,
                    source_platform=site,
                )
                items.append(
                    CrawlItem(
                        source_id=source_id_from_url(url, site),
                        body=body,
                        source_url=url,
                        source_platform=site,
                        crawled_at=now,
                    )
                )
            except Exception as exc:
                logger.exception("Firecrawl failed for %s: %s", url, exc)
        return items
