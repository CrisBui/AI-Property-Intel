"""Shared helpers for PhongTot service fees (water unit-aware storage and matching)."""

from __future__ import annotations

from typing import Any

WATER_UNIT_PER_M3 = "per_m3"
WATER_UNIT_PER_PERSON = "per_person"
WATER_UNIT_INCLUDED = "included"
WATER_UNIT_UNKNOWN = "unknown"


def resolve_water_unit(fees: dict[str, Any]) -> str | None:
    explicit = fees.get("water_unit")
    if isinstance(explicit, str) and explicit:
        return explicit
    if fees.get("water_vnd_per_m3") is not None:
        return WATER_UNIT_PER_M3
    if fees.get("water_vnd_per_person") is not None:
        return WATER_UNIT_PER_PERSON
    return None


def format_water_fee(fees: dict[str, Any]) -> str | None:
    unit = resolve_water_unit(fees)
    if unit == WATER_UNIT_PER_M3:
        value = fees.get("water_vnd_per_m3")
        if value is not None:
            return f"Nước {int(value):,} đ/m³"
    elif unit == WATER_UNIT_PER_PERSON:
        value = fees.get("water_vnd_per_person")
        if value is not None:
            return f"Nước {int(value):,} đ/người"
    elif unit == WATER_UNIT_INCLUDED:
        return "Nước: miễn phí"
    raw = fees.get("water_raw")
    if isinstance(raw, str) and raw.strip():
        return f"Nước: {raw.strip()}"
    return None


def water_matches_filter(fees: dict[str, Any], max_per_m3: int | None, max_per_person: int | None) -> bool:
    """Return False only when listing and filter share the same water unit and fee exceeds max."""
    listing_unit = resolve_water_unit(fees)

    if max_per_m3 is not None:
        if listing_unit != WATER_UNIT_PER_M3:
            return True
        actual = fees.get("water_vnd_per_m3")
        if actual is None:
            return True
        return int(actual) <= max_per_m3

    if max_per_person is not None:
        if listing_unit != WATER_UNIT_PER_PERSON:
            return True
        actual = fees.get("water_vnd_per_person")
        if actual is None:
            return True
        return int(actual) <= max_per_person

    return True


def water_filter_mismatch_note(
    fees: dict[str, Any],
    max_per_m3: int | None,
    max_per_person: int | None,
) -> str | None:
    listing_unit = resolve_water_unit(fees)
    if max_per_m3 is not None and listing_unit not in (None, WATER_UNIT_PER_M3):
        return "Nước: khác đơn vị query (đ/m³)"
    if max_per_person is not None and listing_unit not in (None, WATER_UNIT_PER_PERSON):
        return "Nước: khác đơn vị query (đ/người)"
    return None
