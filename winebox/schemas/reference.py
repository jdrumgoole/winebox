"""Pydantic schemas for reference data (wine types, grape varieties, regions, classifications)."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# WINE TYPE SCHEMAS
# =============================================================================


class WineTypeBase(BaseModel):
    """Base wine type schema."""

    id: str = Field(..., description="Wine type ID (e.g., 'red', 'white')")
    name: str = Field(..., description="Display name")
    description: str | None = Field(None, description="Type description")


class WineTypeResponse(WineTypeBase):
    """Wine type response schema."""

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# GRAPE VARIETY SCHEMAS
# =============================================================================


class GrapeVarietyBase(BaseModel):
    """Base grape variety schema."""

    name: str = Field(..., max_length=100, description="Grape variety name")
    color: str = Field(..., description="Grape color: 'red' or 'white'")
    category: str | None = Field(None, description="Category: 'international' or 'regional'")
    origin_country: str | None = Field(None, description="Country of origin")


class GrapeVarietyCreate(GrapeVarietyBase):
    """Schema for creating a grape variety."""

    pass


class GrapeVarietyResponse(GrapeVarietyBase):
    """Grape variety response schema."""

    id: str = Field(..., description="UUID")

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# REGION SCHEMAS
# =============================================================================


class RegionBase(BaseModel):
    """Base region schema."""

    name: str = Field(..., max_length=100, description="Region name")
    display_name: str = Field(..., max_length=150, description="User-friendly display name")
    country: str | None = Field(None, description="Country (denormalized)")
    level: int = Field(..., ge=0, le=4, description="Hierarchy level (0=country, 1=region, etc.)")


class RegionCreate(RegionBase):
    """Schema for creating a region."""

    parent_id: str | None = Field(None, description="Parent region ID")


class RegionResponse(RegionBase):
    """Region response schema."""

    id: str = Field(..., description="UUID")
    parent_id: str | None = Field(None, description="Parent region ID")

    model_config = ConfigDict(from_attributes=True)


class RegionWithChildren(RegionResponse):
    """Region response with children."""

    children: list["RegionWithChildren"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RegionTree(BaseModel):
    """Full region tree response."""

    regions: list[RegionWithChildren] = Field(..., description="Top-level regions (countries)")


# =============================================================================
# CLASSIFICATION SCHEMAS
# =============================================================================


class ClassificationBase(BaseModel):
    """Base classification schema."""

    name: str = Field(..., max_length=100, description="Classification name")
    display_name: str = Field(..., max_length=150, description="Display name")
    country: str = Field(..., description="Country")
    system: str = Field(..., description="Classification system (e.g., 'bordeaux_1855')")
    level: int | None = Field(None, description="Ordering within system (1=highest)")


class ClassificationCreate(ClassificationBase):
    """Schema for creating a classification."""

    pass


class ClassificationResponse(ClassificationBase):
    """Classification response schema."""

    id: str = Field(..., description="UUID")

    model_config = ConfigDict(from_attributes=True)


class ClassificationsBySystem(BaseModel):
    """Classifications grouped by system."""

    system: str = Field(..., description="System name")
    country: str = Field(..., description="Country")
    classifications: list[ClassificationResponse] = Field(..., description="Classifications in this system")


# =============================================================================
# WINE GRAPE (BLEND) SCHEMAS
# =============================================================================


class WineGrapeBase(BaseModel):
    """Base wine grape (blend component) schema."""

    grape_variety_id: str = Field(..., description="Grape variety UUID")
    percentage: float | None = Field(None, ge=0, le=100, description="Percentage in blend (0-100)")


class WineGrapeCreate(WineGrapeBase):
    """Schema for adding a grape to a wine blend."""

    pass


class WineGrapeResponse(WineGrapeBase):
    """Wine grape response with variety details."""

    id: str = Field(..., description="Junction record UUID")
    grape_variety: GrapeVarietyResponse = Field(..., description="Grape variety details")

    model_config = ConfigDict(from_attributes=True)


class WineGrapeBlend(BaseModel):
    """Complete grape blend for a wine."""

    wine_id: str = Field(..., description="Wine UUID")
    grapes: list[WineGrapeResponse] = Field(default_factory=list)
    total_percentage: float | None = Field(None, description="Sum of percentages (should be ~100)")


class WineGrapeBlendUpdate(BaseModel):
    """Schema for setting/replacing a wine's grape blend."""

    grapes: list[WineGrapeCreate] = Field(..., description="Complete grape blend")


# =============================================================================
# WINE SCORE SCHEMAS
# =============================================================================


class WineScoreBase(BaseModel):
    """Base wine score schema."""

    source: str = Field(..., max_length=100, description="Rating source (e.g., 'wine_advocate')")
    score: int = Field(..., ge=0, le=100, description="Score value")
    score_type: str = Field(..., description="Score type: '100_point', '20_point', or '5_star'")
    review_date: date | None = Field(None, description="Date of review")
    reviewer: str | None = Field(None, max_length=100, description="Reviewer name")
    notes: str | None = Field(None, description="Tasting notes excerpt")


class WineScoreCreate(WineScoreBase):
    """Schema for creating a wine score."""

    pass


class WineScoreUpdate(BaseModel):
    """Schema for updating a wine score."""

    source: str | None = Field(None, max_length=100)
    score: int | None = Field(None, ge=0, le=100)
    score_type: str | None = None
    review_date: date | None = None
    reviewer: str | None = Field(None, max_length=100)
    notes: str | None = None


class WineScoreResponse(WineScoreBase):
    """Wine score response schema."""

    id: str = Field(..., description="UUID")
    wine_id: str = Field(..., description="Wine UUID")
    created_at: datetime = Field(..., description="When score was added")
    normalized_score: float = Field(..., description="Score normalized to 0-100 scale")

    model_config = ConfigDict(from_attributes=True)


class WineScoresResponse(BaseModel):
    """All scores for a wine."""

    wine_id: str = Field(..., description="Wine UUID")
    scores: list[WineScoreResponse] = Field(default_factory=list)
    average_score: float | None = Field(None, description="Average normalized score")


# =============================================================================
# REFERENCE DATA SUMMARY
# =============================================================================


class ReferenceDataSummary(BaseModel):
    """Summary of available reference data."""

    wine_types_count: int = Field(..., description="Number of wine types")
    grape_varieties_count: int = Field(..., description="Number of grape varieties")
    regions_count: int = Field(..., description="Number of regions")
    classifications_count: int = Field(..., description="Number of classifications")


# Enable forward references for recursive model
RegionWithChildren.model_rebuild()
