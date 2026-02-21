"""Pydantic schemas for X-Wines dataset API endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class XWinesWineSearchResult(BaseModel):
    """Wine search result for autocomplete dropdown."""

    id: int = Field(..., description="X-Wines wine ID")
    name: str = Field(..., description="Wine name")
    winery: str | None = Field(None, description="Winery name")
    wine_type: str = Field(..., description="Wine type (Red, White, Rosé, etc.)")
    country: str | None = Field(None, description="Country of origin")
    region: str | None = Field(None, description="Region name")
    abv: float | None = Field(None, description="Alcohol by volume percentage")
    avg_rating: float | None = Field(None, description="Average community rating (1-5)")
    rating_count: int = Field(0, description="Number of ratings")

    model_config = ConfigDict(from_attributes=True)


class XWinesWineDetail(BaseModel):
    """Full wine details from X-Wines dataset."""

    id: int = Field(..., description="X-Wines wine ID")
    name: str = Field(..., description="Wine name")
    wine_type: str = Field(..., description="Wine type (Red, White, Rosé, etc.)")
    elaborate: str | None = Field(None, description="Varietal style (100%, Blend, etc.)")
    grapes: str | None = Field(None, description="Grape varieties (JSON array)")
    harmonize: str | None = Field(None, description="Food pairings")
    abv: float | None = Field(None, description="Alcohol by volume percentage")
    body: str | None = Field(None, description="Body (Light, Medium, Full-bodied)")
    acidity: str | None = Field(None, description="Acidity level")
    country_code: str | None = Field(None, description="ISO country code")
    country: str | None = Field(None, description="Full country name")
    region_id: int | None = Field(None, description="X-Wines region ID")
    region_name: str | None = Field(None, description="Region display name")
    winery_id: int | None = Field(None, description="X-Wines winery ID")
    winery_name: str | None = Field(None, description="Winery display name")
    website: str | None = Field(None, description="Winery website")
    vintages: str | None = Field(None, description="Available vintages (JSON array)")
    avg_rating: float | None = Field(None, description="Average community rating (1-5)")
    rating_count: int = Field(0, description="Number of ratings")

    model_config = ConfigDict(from_attributes=True)


class FacetBucket(BaseModel):
    """A single facet value with its count."""

    value: str = Field(..., description="Facet value")
    count: int = Field(..., description="Number of matching documents")


class SearchFacets(BaseModel):
    """Facet counts returned alongside search results."""

    wine_type: list[FacetBucket] = Field(default_factory=list)
    country: list[FacetBucket] = Field(default_factory=list)


class XWinesSearchResponse(BaseModel):
    """Response for wine search/autocomplete."""

    results: list[XWinesWineSearchResult] = Field(
        default_factory=list, description="Matching wines"
    )
    total: int = Field(0, description="Total number of matches (may be more than returned)")
    skip: int = Field(0, description="Number of results skipped")
    limit: int = Field(10, description="Maximum results per page")
    facets: SearchFacets | None = Field(
        None, description="Facet counts (when Atlas Search is available)"
    )


class XWinesStats(BaseModel):
    """X-Wines dataset statistics."""

    wine_count: int = Field(0, description="Total wines in dataset")
    rating_count: int = Field(0, description="Total ratings in dataset")
    version: str | None = Field(None, description="Dataset version imported")
    import_date: str | None = Field(None, description="Date of import")
    source: str = Field(
        "https://github.com/rogerioxavier/X-Wines",
        description="Dataset source URL"
    )


class XWinesMetadataResponse(BaseModel):
    """X-Wines metadata response."""

    key: str = Field(..., description="Metadata key")
    value: str = Field(..., description="Metadata value")
    updated_at: datetime | None = Field(None, description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)
