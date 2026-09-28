"""Provider-independent NOVA catalog contracts (not playback contracts)."""

from typing import Literal

from pydantic import BaseModel, Field


class Score(BaseModel):
    value: float = Field(ge=0, le=100)
    scale: int = 100
    provider: str = "anilist"


class SourceMapping(BaseModel):
    source: str
    slug: str
    status: Literal["verified"] = "verified"
    verifiedAt: int


class NovaAnime(BaseModel):
    id: str
    slug: str
    providerIds: dict[str, int]
    title: str
    alternativeTitles: list[str] = Field(default_factory=list)
    description: str | None = None
    descriptionLanguage: str | None = None
    image: str | None = None
    banner: str | None = None
    seasonPoster: str | None = None
    animePoster: str | None = None
    seasonBackdrop: str | None = None
    animeBackdrop: str | None = None
    accentColor: str | None = None
    score: Score | None = None
    genres: list[str] = Field(default_factory=list)
    year: int | None = None
    season: str | None = None
    status: Literal["announced", "releasing", "finished", "cancelled", "hiatus", "unknown"]
    type: str | None = None
    episodeCount: int | None = None
    runtime: int | None = None
    country: str | None = None
    studios: list[str] = Field(default_factory=list)
    trailer: str | None = None
    popularity: int | None = None
    metadataUpdatedAt: int
    # A verified title mapping alone does not prove episode availability.
    availability: Literal["unknown"] = "unknown"
    availableEpisodeCount: int | None = None
    sourceMappings: list[SourceMapping] = Field(default_factory=list)


class AnimePage(BaseModel):
    items: list[NovaAnime]
    page: int
    perPage: int
    hasNextPage: bool


class CatalogHome(BaseModel):
    featured: list[NovaAnime]
    topRated: list[NovaAnime]
    discover: AnimePage


class CacheInfo(BaseModel):
    status: Literal["miss", "fresh", "stale"]
    updatedAt: int
    expiresAt: int
    staleUntil: int


class HomeResponse(BaseModel):
    data: CatalogHome
    cache: CacheInfo


class PageResponse(BaseModel):
    data: AnimePage
    cache: CacheInfo


class DetailResponse(BaseModel):
    data: NovaAnime
    cache: CacheInfo
