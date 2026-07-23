from pydantic import BaseModel, Field


class AmenityStat(BaseModel):
    amenity: str
    count: int
    pct: float


class AreaMarketStats(BaseModel):
    area_key: str
    listing_count: int
    priced_count: int
    price_min_vnd: int | None = None
    price_max_vnd: int | None = None
    price_avg_vnd: int | None = None
    top_amenities: list[AmenityStat] = Field(default_factory=list)


class MarketReport(BaseModel):
    total_listings: int
    areas: list[AreaMarketStats] = Field(default_factory=list)
    filter_landmark: str | None = None
