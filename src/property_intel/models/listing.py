from datetime import datetime

from pydantic import BaseModel, Field


class Listing(BaseModel):
    source_id: str
    title: str
    description_raw: str
    price_vnd: int | None = None
    area_m2: float | None = None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    district: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    amenities: list[str] = Field(default_factory=list)
    near_landmarks: list[str] = Field(default_factory=list)
    common_amenities: list[str] = Field(default_factory=list)
    room_layout_tags: list[str] = Field(default_factory=list)
    service_fees: dict[str, int | str | None] = Field(default_factory=dict)
    building: dict[str, int | None] = Field(default_factory=dict)
    source_url: str | None = None
    contact_phone: str | None = None
    short_description: str | None = None
    description_long: str | None = None
    price_note: str | None = None
    images: list[str] = Field(default_factory=list)
    sentiment_notes: str | None = None
    extract_confidence: float = 0.0
    posted_at: datetime | None = None


class MatchFilters(BaseModel):
    """Structured search filters parsed from natural language (web-filter style)."""

    price_max: int | None = None
    price_min: int | None = None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    amenities_required: list[str] = Field(default_factory=list)
    room_layout_tags: list[str] = Field(default_factory=list)
    common_amenities_required: list[str] = Field(default_factory=list)
    electricity_max_vnd_per_kwh: int | None = None
    water_max_vnd_per_m3: int | None = None
    water_max_vnd_per_person: int | None = None
    internet_max_vnd_per_room: int | None = None
    min_floor_count: int | None = None
    max_floor_count: int | None = None
    min_room_count: int | None = None
    district: str | None = None
    districts: list[str] = Field(default_factory=list)
    landmark: str | None = None
    soft_prefs: str | None = None


class MatchResult(BaseModel):
    source_id: str
    title: str
    price_vnd: int | None
    district: str | None
    address_text: str | None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    amenities: list[str]
    room_layout_tags: list[str] = Field(default_factory=list)
    common_amenities: list[str] = Field(default_factory=list)
    service_fees: dict[str, int | str | None] = Field(default_factory=dict)
    near_landmarks: list[str]
    source_url: str | None = None
    contact_phone: str | None = None
    short_description: str | None = None
    score: float
    rationale: str
