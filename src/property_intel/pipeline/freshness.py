"""Parse listing freshness timestamps and filter stale results."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_UPDATED_RE = re.compile(
    r"Cập nhật\s+(\d+)\s+(phút|giờ|ngày|tuần|tháng)\s+trước",
    re.I,
)


def parse_posted_at(text: str | None, reference: datetime | None) -> datetime | None:
    """Convert NhaTot-style 'Cập nhật X giờ trước' to an absolute UTC datetime."""
    if not text or reference is None:
        return None

    match = _UPDATED_RE.search(text)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    ref = reference if reference.tzinfo is not None else reference.replace(tzinfo=timezone.utc)
    deltas = {
        "phút": timedelta(minutes=amount),
        "giờ": timedelta(hours=amount),
        "ngày": timedelta(days=amount),
        "tuần": timedelta(weeks=amount),
        "tháng": timedelta(days=amount * 30),
    }
    delta = deltas.get(unit)
    if delta is None:
        return None
    return ref - delta


def listing_freshness_at(
    *,
    last_seen_at: datetime | None,
    posted_at: datetime | None,
    crawled_at: datetime | None,
) -> datetime | None:
    """Best-effort freshness timestamp for search filtering."""
    return last_seen_at or posted_at or crawled_at


def is_listing_fresh(
    freshness_at: datetime | None,
    *,
    max_age_days: int,
    now: datetime | None = None,
) -> bool:
    """Return True when listing is within max_age_days or freshness is unknown."""
    if max_age_days <= 0 or freshness_at is None:
        return True
    current = now or datetime.now(timezone.utc)
    if freshness_at.tzinfo is None:
        freshness_at = freshness_at.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=max_age_days)
    return freshness_at >= cutoff
