from typing import Literal

from pydantic import BaseModel, Field

from property_intel.models.listing import MatchFilters

SearchSort = Literal["price_asc", "price_desc", "area_asc", "area_desc"]


class SearchRequest(BaseModel):
    districts: list[str] = Field(default_factory=list)
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    area_min_m2: float | None = Field(default=None, ge=0)
    area_max_m2: float | None = Field(default=None, ge=0)
    room_layout_tags: list[str] = Field(default_factory=list)
    amenities_required: list[str] = Field(default_factory=list)
    common_amenities_required: list[str] = Field(default_factory=list)
    electricity_max_vnd_per_kwh: int | None = Field(default=None, ge=0)
    water_max_vnd_per_m3: int | None = Field(default=None, ge=0)
    water_max_vnd_per_person: int | None = Field(default=None, ge=0)
    internet_max_vnd_per_room: int | None = Field(default=None, ge=0)
    q: str | None = Field(default=None, max_length=200)
    sort: SearchSort = "price_asc"
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class ListingCard(BaseModel):
    source_id: str
    title: str
    district: str | None = None
    address_text: str | None = None
    price_vnd: int | None = None
    area_min_m2: float | None = None
    area_max_m2: float | None = None
    room_layout_tags: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    common_amenities: list[str] = Field(default_factory=list)
    service_fees_summary: list[str] = Field(default_factory=list)
    contact_phone: str | None = None
    source_url: str | None = None
    source_platform: str | None = None
    short_description: str | None = None
    thumbnail_url: str | None = None


class ListingDetail(ListingCard):
    description_long: str | None = None
    price_note: str | None = None
    near_landmarks: list[str] = Field(default_factory=list)
    service_fees: dict[str, int | str | None] = Field(default_factory=dict)
    building: dict[str, int | None] = Field(default_factory=dict)
    images: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    total: int
    page: int
    size: int
    sort: SearchSort
    filters_applied: MatchFilters
    items: list[ListingCard]


class RangePreset(BaseModel):
    id: str
    label: str
    min: int | float | None = None
    max: int | float | None = None


class RoomLayoutOption(BaseModel):
    id: str
    label: str
    tags: list[str]


class AmenityOption(BaseModel):
    id: str
    label: str


class SearchMetaResponse(BaseModel):
    districts: list[str]
    price_presets: list[RangePreset]
    area_presets: list[RangePreset]
    room_layout_options: list[RoomLayoutOption]
    amenity_options: list[AmenityOption]
    sort_options: list[dict[str, str]]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatClientState(BaseModel):
    last_filters: MatchFilters | None = None
    last_result_ids: list[str] = Field(default_factory=list)
    focused_source_id: str | None = None
    compared_listing_ids: list[str] = Field(default_factory=list)
    user_preferences: dict[str, str | int | float | list[str] | None] = Field(default_factory=dict)


class SearchPageContext(BaseModel):
    """Current search UI state sent with each chat turn."""

    total: int = 0
    page: int = 1
    filters_summary: str | None = None
    visible_listings: list[ListingCard] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str | None = None
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    client_state: ChatClientState | None = None
    page_context: SearchPageContext | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    cards: list[ListingCard] = Field(default_factory=list)
    filters_applied: MatchFilters | None = None
    client_state: ChatClientState
    tool_calls: list[str] = Field(default_factory=list)
