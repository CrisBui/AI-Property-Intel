from property_intel.api.schemas import (
    AmenityOption,
    RangePreset,
    RoomLayoutOption,
    SearchMetaResponse,
)
from property_intel.pipeline.vietnamese_utils import HANOI_DISTRICT_SLUGS

TENANT_DISTRICTS = [
    HANOI_DISTRICT_SLUGS["cau-giay"],
    HANOI_DISTRICT_SLUGS["nam-tu-liem"],
    HANOI_DISTRICT_SLUGS["ba-dinh"],
    HANOI_DISTRICT_SLUGS["ha-dong"],
    HANOI_DISTRICT_SLUGS["dong-da"],
    HANOI_DISTRICT_SLUGS["bac-tu-liem"],
    HANOI_DISTRICT_SLUGS["thanh-xuan"],
    HANOI_DISTRICT_SLUGS["tay-ho"],
    HANOI_DISTRICT_SLUGS["hoang-mai"],
    HANOI_DISTRICT_SLUGS["hai-ba-trung"],
    HANOI_DISTRICT_SLUGS["hoan-kiem"],
    HANOI_DISTRICT_SLUGS["long-bien"],
]

PRICE_PRESETS = [
    RangePreset(id="all", label="Tất cả mức giá", min=0, max=None),
    RangePreset(id="under_3m", label="Dưới 3 triệu", min=None, max=3_000_000),
    RangePreset(id="3_5m", label="3 - 5 triệu", min=3_000_000, max=5_000_000),
    RangePreset(id="5_7m", label="5 - 7 triệu", min=5_000_000, max=7_000_000),
    RangePreset(id="7_10m", label="7 - 10 triệu", min=7_000_000, max=10_000_000),
    RangePreset(id="10_15m", label="10 - 15 triệu", min=10_000_000, max=15_000_000),
    RangePreset(id="over_15m", label="Trên 15 triệu", min=15_000_000, max=None),
]

AREA_PRESETS = [
    RangePreset(id="all", label="Tất cả diện tích", min=None, max=None),
    RangePreset(id="under_20", label="Dưới 20m²", min=None, max=20),
    RangePreset(id="20_30", label="20 - 30m²", min=20, max=30),
    RangePreset(id="30_40", label="30 - 40m²", min=30, max=40),
    RangePreset(id="over_40", label="Trên 40m²", min=40, max=None),
]

ROOM_LAYOUT_OPTIONS = [
    RoomLayoutOption(id="studio", label="Studio", tags=["studio"]),
    RoomLayoutOption(id="1bed", label="1 phòng ngủ", tags=["1_ngu_1_khach"]),
    RoomLayoutOption(id="2bed", label="2 phòng ngủ", tags=["2_phong_ngu"]),
    RoomLayoutOption(id="co_bep", label="Có bếp", tags=["co_bep"]),
]

AMENITY_OPTIONS = [
    AmenityOption(id="bep", label="Bếp"),
    AmenityOption(id="dieu_hoa", label="Điều hòa"),
    AmenityOption(id="may_giat", label="Máy giặt"),
    AmenityOption(id="nong_lanh", label="Nóng lạnh"),
    AmenityOption(id="ban_cong", label="Ban công"),
]

SORT_OPTIONS = [
    {"id": "price_asc", "label": "Giá thấp → cao"},
    {"id": "price_desc", "label": "Giá cao → thấp"},
    {"id": "area_asc", "label": "Diện tích nhỏ → lớn"},
    {"id": "area_desc", "label": "Diện tích lớn → nhỏ"},
]


def get_search_meta() -> SearchMetaResponse:
    return SearchMetaResponse(
        districts=TENANT_DISTRICTS,
        price_presets=PRICE_PRESETS,
        area_presets=AREA_PRESETS,
        room_layout_options=ROOM_LAYOUT_OPTIONS,
        amenity_options=AMENITY_OPTIONS,
        sort_options=SORT_OPTIONS,
    )
