from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import select

from property_intel.config import get_settings
from property_intel.db.models import RawListingRow
from property_intel.db.session import session_scope
from property_intel.pipeline.crawl.discovery import run_discover
from property_intel.pipeline.crawl.base import CrawlItem, CrawlSource, is_allowed_crawl_url, load_urls_file
from property_intel.pipeline.crawl.sources import FirecrawlSource, UrlFetchSource

logger = logging.getLogger(__name__)

CrawlSourceName = Literal["firecrawl", "url-fetch"]


def get_crawl_source(name: CrawlSourceName) -> CrawlSource:
    if name == "firecrawl":
        return FirecrawlSource()
    if name == "url-fetch":
        return UrlFetchSource()
    raise ValueError(f"Unknown crawl source: {name}")


def _upsert_crawl_item(session, item: CrawlItem, now: datetime) -> str:
    existing = session.scalar(
        select(RawListingRow).where(RawListingRow.source_id == item.source_id)
    )
    if existing is None:
        session.add(
            RawListingRow(
                source_id=item.source_id,
                body=item.body,
                source_platform=item.source_platform,
                source_url=item.source_url,
                crawled_at=item.crawled_at,
                last_seen_at=now,
                extracted=False,
                extract_status="pending",
            )
        )
        return "inserted"

    existing.last_seen_at = now
    if existing.body != item.body:
        existing.body = item.body
        existing.extracted = False
        existing.extract_status = "pending"
        existing.crawled_at = item.crawled_at
        if item.source_url:
            existing.source_url = item.source_url
        return "updated"

    return "skipped"


def run_crawl(
    source_name: CrawlSourceName,
    urls_file: str | None = None,
    rate_limit_seconds: float | None = None,
    discover_first: bool = False,
    search_urls_file: str | None = None,
    max_links_per_page: int = 30,
) -> dict[str, int]:
    settings = get_settings()

    if discover_first:
        search_path = (
            search_urls_file
            or str(settings.crawl_search_urls_file_resolved)
        )
        discover_stats = run_discover(
            search_urls_file=search_path,
            output_file=str(settings.crawl_urls_file_resolved),
            max_links_per_page=max_links_per_page,
        )
        if discover_stats["discovered"] == 0:
            return {
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "total_urls": 0,
                "discovered": 0,
            }

    path = (
        Path(urls_file).resolve()
        if urls_file is not None and not discover_first
        else settings.crawl_urls_file_resolved
    )
    urls = load_urls_file(path)
    if not urls:
        logger.warning("No URLs in %s", path)
        return {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0, "total_urls": 0}

    source = get_crawl_source(source_name)
    delay = rate_limit_seconds if rate_limit_seconds is not None else settings.crawl_rate_limit_seconds

    inserted = 0
    updated = 0
    skipped = 0
    failed = 0

    for index, url in enumerate(urls):
        if not is_allowed_crawl_url(url):
            logger.warning("Skipping unsupported crawl URL: %s", url)
            failed += 1
            continue

        if index > 0 and delay > 0:
            time.sleep(delay)

        try:
            items = source.fetch_items([url])
        except Exception as exc:
            logger.exception("Crawl source error for %s: %s", url, exc)
            failed += 1
            continue

        if not items:
            failed += 1
            continue

        now = datetime.now(timezone.utc)
        with session_scope() as session:
            for item in items:
                result = _upsert_crawl_item(session, item, now)
                if result == "inserted":
                    inserted += 1
                    logger.info("Crawled new %s from %s", item.source_id, url)
                elif result == "updated":
                    updated += 1
                    logger.info("Crawled updated %s from %s", item.source_id, url)
                else:
                    skipped += 1
                    logger.info("Crawled unchanged %s from %s", item.source_id, url)

    stats = {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "total_urls": len(urls),
    }
    if discover_first:
        stats["discovered"] = discover_stats["discovered"]
    logger.info(
        "Crawl complete: inserted=%d updated=%d skipped=%d failed=%d urls=%d",
        inserted,
        updated,
        skipped,
        failed,
        len(urls),
    )
    return stats
