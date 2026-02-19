"""Reference data API router for wine types, grape varieties, regions, and classifications."""

import re

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, Query

from winebox.models import Classification, GrapeVariety, Region, WineType
from winebox.schemas.reference import (
    ClassificationResponse,
    ClassificationsBySystem,
    GrapeVarietyResponse,
    ReferenceDataSummary,
    RegionResponse,
    RegionTree,
    RegionWithChildren,
    WineTypeResponse,
)

router = APIRouter()


# =============================================================================
# WINE TYPES
# =============================================================================


@router.get("/wine-types", response_model=list[WineTypeResponse])
async def list_wine_types() -> list[WineTypeResponse]:
    """List all wine types."""
    wine_types = await WineType.find().sort(WineType.name).to_list()
    return [
        WineTypeResponse(
            id=wt.type_id,
            name=wt.name,
            description=wt.description,
        )
        for wt in wine_types
    ]


@router.get("/wine-types/{type_id}", response_model=WineTypeResponse)
async def get_wine_type(type_id: str) -> WineTypeResponse:
    """Get a specific wine type by ID."""
    wine_type = await WineType.find_one(WineType.type_id == type_id)
    if not wine_type:
        raise HTTPException(status_code=404, detail="Wine type not found")
    return WineTypeResponse(
        id=wine_type.type_id,
        name=wine_type.name,
        description=wine_type.description,
    )


# =============================================================================
# GRAPE VARIETIES
# =============================================================================


@router.get("/grape-varieties", response_model=list[GrapeVarietyResponse])
async def list_grape_varieties(
    color: str | None = Query(None, description="Filter by color: 'red' or 'white'"),
    category: str | None = Query(None, description="Filter by category: 'international' or 'regional'"),
    search: str | None = Query(None, description="Search by name (partial match)"),
) -> list[GrapeVarietyResponse]:
    """List grape varieties with optional filters."""
    conditions = {}

    if color:
        conditions["color"] = color
    if category:
        conditions["category"] = category
    if search:
        conditions["name"] = {"$regex": re.compile(re.escape(search), re.IGNORECASE)}

    varieties = await GrapeVariety.find(conditions).sort(GrapeVariety.name).to_list()
    return [
        GrapeVarietyResponse(
            id=str(v.id),
            name=v.name,
            color=v.color,
            category=v.category,
            origin_country=v.origin_country,
        )
        for v in varieties
    ]


@router.get("/grape-varieties/{variety_id}", response_model=GrapeVarietyResponse)
async def get_grape_variety(variety_id: str) -> GrapeVarietyResponse:
    """Get a specific grape variety by ID."""
    try:
        variety = await GrapeVariety.get(PydanticObjectId(variety_id))
    except Exception:
        variety = None

    if not variety:
        raise HTTPException(status_code=404, detail="Grape variety not found")

    return GrapeVarietyResponse(
        id=str(variety.id),
        name=variety.name,
        color=variety.color,
        category=variety.category,
        origin_country=variety.origin_country,
    )


# =============================================================================
# REGIONS
# =============================================================================


@router.get("/regions", response_model=list[RegionResponse])
async def list_regions(
    country: str | None = Query(None, description="Filter by country"),
    level: int | None = Query(None, ge=0, le=4, description="Filter by hierarchy level"),
    parent_id: str | None = Query(None, description="Filter by parent region ID"),
    search: str | None = Query(None, description="Search by name (partial match)"),
) -> list[RegionResponse]:
    """List regions with optional filters."""
    conditions = {}

    if country:
        conditions["country"] = country
    if level is not None:
        conditions["level"] = level
    if parent_id:
        try:
            conditions["parent_id"] = PydanticObjectId(parent_id)
        except Exception:
            pass
    if search:
        conditions["display_name"] = {"$regex": re.compile(re.escape(search), re.IGNORECASE)}

    regions = await Region.find(conditions).sort(
        [(Region.level, 1), (Region.display_name, 1)]
    ).to_list()

    return [
        RegionResponse(
            id=str(r.id),
            name=r.name,
            display_name=r.display_name,
            country=r.country,
            level=r.level,
            parent_id=str(r.parent_id) if r.parent_id else None,
        )
        for r in regions
    ]


@router.get("/regions/tree", response_model=RegionTree)
async def get_region_tree(
    country: str | None = Query(None, description="Filter tree by country"),
) -> RegionTree:
    """Get hierarchical region tree starting from countries."""
    conditions = {}
    if country:
        conditions["country"] = country

    all_regions = await Region.find(conditions).sort(
        [(Region.level, 1), (Region.display_name, 1)]
    ).to_list()

    # Build tree structure
    regions_by_id: dict[str, RegionWithChildren] = {}
    root_regions: list[RegionWithChildren] = []

    # First pass: create all nodes
    for region in all_regions:
        node = RegionWithChildren(
            id=str(region.id),
            name=region.name,
            display_name=region.display_name,
            country=region.country,
            level=region.level,
            parent_id=str(region.parent_id) if region.parent_id else None,
            children=[],
        )
        regions_by_id[str(region.id)] = node

    # Second pass: build hierarchy
    for region in all_regions:
        node = regions_by_id[str(region.id)]
        if region.parent_id and str(region.parent_id) in regions_by_id:
            regions_by_id[str(region.parent_id)].children.append(node)
        elif region.level == 0:  # Country level
            root_regions.append(node)

    return RegionTree(regions=root_regions)


@router.get("/regions/{region_id}", response_model=RegionResponse)
async def get_region(region_id: str) -> RegionResponse:
    """Get a specific region by ID."""
    try:
        region = await Region.get(PydanticObjectId(region_id))
    except Exception:
        region = None

    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    return RegionResponse(
        id=str(region.id),
        name=region.name,
        display_name=region.display_name,
        country=region.country,
        level=region.level,
        parent_id=str(region.parent_id) if region.parent_id else None,
    )


@router.get("/regions/{region_id}/children", response_model=list[RegionResponse])
async def get_region_children(region_id: str) -> list[RegionResponse]:
    """Get child regions of a specific region."""
    # Verify parent exists
    try:
        parent = await Region.get(PydanticObjectId(region_id))
    except Exception:
        parent = None

    if not parent:
        raise HTTPException(status_code=404, detail="Region not found")

    # Get children
    children = await Region.find(
        Region.parent_id == parent.id
    ).sort(Region.display_name).to_list()

    return [
        RegionResponse(
            id=str(c.id),
            name=c.name,
            display_name=c.display_name,
            country=c.country,
            level=c.level,
            parent_id=str(c.parent_id) if c.parent_id else None,
        )
        for c in children
    ]


@router.get("/regions/{region_id}/path", response_model=list[RegionResponse])
async def get_region_path(region_id: str) -> list[RegionResponse]:
    """Get full path from country to this region."""
    try:
        region = await Region.get(PydanticObjectId(region_id))
    except Exception:
        region = None

    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    # Build path from current to root
    path = []
    current = region
    while current:
        path.insert(0, RegionResponse(
            id=str(current.id),
            name=current.name,
            display_name=current.display_name,
            country=current.country,
            level=current.level,
            parent_id=str(current.parent_id) if current.parent_id else None,
        ))
        if current.parent_id:
            current = await Region.get(current.parent_id)
        else:
            current = None

    return path


# =============================================================================
# CLASSIFICATIONS
# =============================================================================


@router.get("/classifications", response_model=list[ClassificationResponse])
async def list_classifications(
    country: str | None = Query(None, description="Filter by country"),
    system: str | None = Query(None, description="Filter by classification system"),
) -> list[ClassificationResponse]:
    """List classifications with optional filters."""
    conditions = {}

    if country:
        conditions["country"] = country
    if system:
        conditions["system"] = system

    classifications = await Classification.find(conditions).sort(
        [(Classification.country, 1), (Classification.system, 1), (Classification.level, 1)]
    ).to_list()

    return [
        ClassificationResponse(
            id=str(c.id),
            name=c.name,
            display_name=c.display_name,
            country=c.country,
            system=c.system,
            level=c.level,
        )
        for c in classifications
    ]


@router.get("/classifications/by-system", response_model=list[ClassificationsBySystem])
async def list_classifications_by_system(
    country: str | None = Query(None, description="Filter by country"),
) -> list[ClassificationsBySystem]:
    """List classifications grouped by system."""
    conditions = {}

    if country:
        conditions["country"] = country

    classifications = await Classification.find(conditions).sort(
        [(Classification.country, 1), (Classification.system, 1), (Classification.level, 1)]
    ).to_list()

    # Group by system
    systems: dict[str, ClassificationsBySystem] = {}
    for c in classifications:
        key = f"{c.country}:{c.system}"
        if key not in systems:
            systems[key] = ClassificationsBySystem(
                system=c.system,
                country=c.country,
                classifications=[],
            )
        systems[key].classifications.append(ClassificationResponse(
            id=str(c.id),
            name=c.name,
            display_name=c.display_name,
            country=c.country,
            system=c.system,
            level=c.level,
        ))

    return list(systems.values())


@router.get("/classifications/{classification_id}", response_model=ClassificationResponse)
async def get_classification(classification_id: str) -> ClassificationResponse:
    """Get a specific classification by ID."""
    try:
        classification = await Classification.get(PydanticObjectId(classification_id))
    except Exception:
        classification = None

    if not classification:
        raise HTTPException(status_code=404, detail="Classification not found")

    return ClassificationResponse(
        id=str(classification.id),
        name=classification.name,
        display_name=classification.display_name,
        country=classification.country,
        system=classification.system,
        level=classification.level,
    )


# =============================================================================
# SUMMARY
# =============================================================================


@router.get("/summary", response_model=ReferenceDataSummary)
async def get_reference_summary() -> ReferenceDataSummary:
    """Get summary of available reference data."""
    wine_types_count = await WineType.count()
    grape_count = await GrapeVariety.count()
    regions_count = await Region.count()
    classifications_count = await Classification.count()

    return ReferenceDataSummary(
        wine_types_count=wine_types_count,
        grape_varieties_count=grape_count,
        regions_count=regions_count,
        classifications_count=classifications_count,
    )
