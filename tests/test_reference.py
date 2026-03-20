"""Tests for the reference data API router."""

import pytest
import pytest_asyncio

from winebox.models import Classification, GrapeVariety, Region, WineType


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def seed_wine_types(init_test_db):
    """Seed wine types for testing (idempotent)."""
    types_data = [
        {"type_id": "red", "name": "Red", "description": "Red wines"},
        {"type_id": "white", "name": "White", "description": "White wines"},
        {"type_id": "rose", "name": "Rosé", "description": "Rosé wines"},
    ]
    types = []
    for td in types_data:
        existing = await WineType.find_one({"type_id": td["type_id"]})
        if existing:
            types.append(existing)
        else:
            wt = WineType(**td)
            await wt.insert()
            types.append(wt)
    return types


@pytest_asyncio.fixture
async def seed_grape_varieties(init_test_db):
    """Seed grape varieties for testing (idempotent)."""
    varieties_data = [
        {"name": "Cabernet Sauvignon", "color": "red", "category": "international", "origin_country": "France"},
        {"name": "Merlot", "color": "red", "category": "international", "origin_country": "France"},
        {"name": "Chardonnay", "color": "white", "category": "international", "origin_country": "France"},
        {"name": "Riesling", "color": "white", "category": "regional", "origin_country": "Germany"},
    ]
    varieties = []
    for vd in varieties_data:
        existing = await GrapeVariety.find_one({"name": vd["name"]})
        if existing:
            varieties.append(existing)
        else:
            v = GrapeVariety(**vd)
            await v.insert()
            varieties.append(v)
    return varieties


@pytest_asyncio.fixture
async def seed_regions(init_test_db):
    """Seed regions with hierarchy for testing (idempotent)."""
    # France (level 0)
    france = await Region.find_one({"name": "france", "level": 0})
    if not france:
        france = Region(name="france", display_name="France", level=0, country="France")
        await france.insert()

    # Bordeaux (level 1, child of France)
    bordeaux = await Region.find_one({"name": "bordeaux", "level": 1})
    if not bordeaux:
        bordeaux = Region(
            name="bordeaux", display_name="Bordeaux", level=1,
            parent_id=france.id, country="France",
        )
        await bordeaux.insert()

    # Médoc (level 2, child of Bordeaux)
    medoc = await Region.find_one({"name": "medoc", "level": 2})
    if not medoc:
        medoc = Region(
            name="medoc", display_name="Médoc", level=2,
            parent_id=bordeaux.id, country="France",
        )
        await medoc.insert()

    # Italy (level 0)
    italy = await Region.find_one({"name": "italy", "level": 0})
    if not italy:
        italy = Region(name="italy", display_name="Italy", level=0, country="Italy")
        await italy.insert()

    # Tuscany (level 1, child of Italy)
    tuscany = await Region.find_one({"name": "tuscany", "level": 1})
    if not tuscany:
        tuscany = Region(
            name="tuscany", display_name="Tuscany", level=1,
            parent_id=italy.id, country="Italy",
        )
        await tuscany.insert()

    return {
        "france": france,
        "bordeaux": bordeaux,
        "medoc": medoc,
        "italy": italy,
        "tuscany": tuscany,
    }


@pytest_asyncio.fixture
async def seed_classifications(init_test_db):
    """Seed classifications for testing (idempotent)."""
    classifications_data = [
        {
            "name": "premier_cru", "display_name": "Premier Cru Classé",
            "country": "France", "system": "bordeaux_1855", "level": 1,
        },
        {
            "name": "deuxieme_cru", "display_name": "Deuxième Cru Classé",
            "country": "France", "system": "bordeaux_1855", "level": 2,
        },
        {
            "name": "docg", "display_name": "DOCG",
            "country": "Italy", "system": "italy_quality", "level": 1,
        },
        {
            "name": "doc", "display_name": "DOC",
            "country": "Italy", "system": "italy_quality", "level": 2,
        },
    ]
    classifications = []
    for cd in classifications_data:
        existing = await Classification.find_one(
            {"name": cd["name"], "system": cd["system"]}
        )
        if existing:
            classifications.append(existing)
        else:
            c = Classification(**cd)
            await c.insert()
            classifications.append(c)
    return classifications


# =============================================================================
# Wine Types
# =============================================================================


class TestWineTypes:
    """Tests for wine type endpoints."""

    @pytest.mark.asyncio
    async def test_list_wine_types(self, client, seed_wine_types):
        resp = await client.get("/api/reference/wine-types")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3
        names = [wt["name"] for wt in data]
        assert "Red" in names
        assert "White" in names
        assert "Rosé" in names
        # Should be sorted by name
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_list_wine_types_returns_200(self, client):
        resp = await client.get("/api/reference/wine-types")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_wine_type(self, client, seed_wine_types):
        resp = await client.get("/api/reference/wine-types/red")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "red"
        assert data["name"] == "Red"
        assert data["description"] == "Red wines"

    @pytest.mark.asyncio
    async def test_get_wine_type_not_found(self, client, seed_wine_types):
        resp = await client.get("/api/reference/wine-types/sparkling")
        assert resp.status_code == 404


# =============================================================================
# Grape Varieties
# =============================================================================


class TestGrapeVarieties:
    """Tests for grape variety endpoints."""

    @pytest.mark.asyncio
    async def test_list_grape_varieties(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 4
        names = [g["name"] for g in data]
        assert "Cabernet Sauvignon" in names
        assert "Merlot" in names
        assert "Chardonnay" in names
        assert "Riesling" in names

    @pytest.mark.asyncio
    async def test_list_grape_varieties_filter_color(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties?color=red")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        assert all(g["color"] == "red" for g in data)
        names = [g["name"] for g in data]
        assert "Cabernet Sauvignon" in names
        assert "Merlot" in names

    @pytest.mark.asyncio
    async def test_list_grape_varieties_filter_category(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties?category=regional")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(g["category"] == "regional" for g in data)
        names = [g["name"] for g in data]
        assert "Riesling" in names

    @pytest.mark.asyncio
    async def test_list_grape_varieties_search(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties?search=cab")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Cabernet Sauvignon"

    @pytest.mark.asyncio
    async def test_list_grape_varieties_search_case_insensitive(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties?search=MERLOT")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Merlot"

    @pytest.mark.asyncio
    async def test_get_grape_variety(self, client, seed_grape_varieties):
        variety_id = str(seed_grape_varieties[0].id)
        resp = await client.get(f"/api/reference/grape-varieties/{variety_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Cabernet Sauvignon"
        assert data["color"] == "red"

    @pytest.mark.asyncio
    async def test_get_grape_variety_not_found(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties/000000000000000000000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_grape_variety_invalid_id(self, client, seed_grape_varieties):
        resp = await client.get("/api/reference/grape-varieties/invalid-id")
        assert resp.status_code == 404


# =============================================================================
# Regions
# =============================================================================


class TestRegions:
    """Tests for region endpoints."""

    @pytest.mark.asyncio
    async def test_list_regions(self, client, seed_regions):
        resp = await client.get("/api/reference/regions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 5
        names = [r["name"] for r in data]
        assert "france" in names
        assert "bordeaux" in names
        assert "medoc" in names
        assert "italy" in names
        assert "tuscany" in names

    @pytest.mark.asyncio
    async def test_list_regions_filter_country(self, client, seed_regions):
        resp = await client.get("/api/reference/regions?country=France")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3
        assert all(r["country"] == "France" for r in data)
        names = [r["name"] for r in data]
        assert "france" in names
        assert "bordeaux" in names
        assert "medoc" in names

    @pytest.mark.asyncio
    async def test_list_regions_filter_level(self, client, seed_regions):
        resp = await client.get("/api/reference/regions?level=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        names = [r["name"] for r in data]
        assert "france" in names
        assert "italy" in names

    @pytest.mark.asyncio
    async def test_list_regions_filter_parent(self, client, seed_regions):
        france_id = str(seed_regions["france"].id)
        resp = await client.get(f"/api/reference/regions?parent_id={france_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "bordeaux"

    @pytest.mark.asyncio
    async def test_list_regions_search(self, client, seed_regions):
        resp = await client.get("/api/reference/regions?search=bord")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["display_name"] == "Bordeaux"

    @pytest.mark.asyncio
    async def test_get_region(self, client, seed_regions):
        bordeaux_id = str(seed_regions["bordeaux"].id)
        resp = await client.get(f"/api/reference/regions/{bordeaux_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Bordeaux"
        assert data["level"] == 1

    @pytest.mark.asyncio
    async def test_get_region_not_found(self, client, seed_regions):
        resp = await client.get("/api/reference/regions/000000000000000000000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_region_invalid_id(self, client, seed_regions):
        resp = await client.get("/api/reference/regions/bad-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_region_children(self, client, seed_regions):
        france_id = str(seed_regions["france"].id)
        resp = await client.get(f"/api/reference/regions/{france_id}/children")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "bordeaux"

    @pytest.mark.asyncio
    async def test_get_region_children_not_found(self, client, seed_regions):
        resp = await client.get("/api/reference/regions/000000000000000000000000/children")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_region_path(self, client, seed_regions):
        medoc_id = str(seed_regions["medoc"].id)
        resp = await client.get(f"/api/reference/regions/{medoc_id}/path")
        assert resp.status_code == 200
        data = resp.json()
        # Path should be: France -> Bordeaux -> Médoc
        assert len(data) == 3
        assert data[0]["display_name"] == "France"
        assert data[1]["display_name"] == "Bordeaux"
        assert data[2]["display_name"] == "Médoc"

    @pytest.mark.asyncio
    async def test_get_region_path_root(self, client, seed_regions):
        france_id = str(seed_regions["france"].id)
        resp = await client.get(f"/api/reference/regions/{france_id}/path")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["display_name"] == "France"

    @pytest.mark.asyncio
    async def test_get_region_path_not_found(self, client, seed_regions):
        resp = await client.get("/api/reference/regions/000000000000000000000000/path")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_region_tree(self, client, seed_regions):
        resp = await client.get("/api/reference/regions/tree")
        assert resp.status_code == 200
        data = resp.json()
        # Check that France and Italy are present as roots
        root_names = [r["name"] for r in data["regions"]]
        assert "france" in root_names
        assert "italy" in root_names
        # France should have Bordeaux as child
        france = next(r for r in data["regions"] if r["name"] == "france")
        assert len(france["children"]) == 1
        assert france["children"][0]["name"] == "bordeaux"
        # Bordeaux should have Médoc as child
        assert len(france["children"][0]["children"]) == 1
        assert france["children"][0]["children"][0]["display_name"] == "Médoc"

    @pytest.mark.asyncio
    async def test_get_region_tree_filter_country(self, client, seed_regions):
        resp = await client.get("/api/reference/regions/tree?country=Italy")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["regions"]) >= 1
        italy_roots = [r for r in data["regions"] if r["name"] == "italy"]
        assert len(italy_roots) == 1


# =============================================================================
# Classifications
# =============================================================================


class TestClassifications:
    """Tests for classification endpoints."""

    @pytest.mark.asyncio
    async def test_list_classifications(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 4
        names = [c["name"] for c in data]
        assert "premier_cru" in names
        assert "deuxieme_cru" in names
        assert "docg" in names
        assert "doc" in names

    @pytest.mark.asyncio
    async def test_list_classifications_filter_country(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications?country=France")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        assert all(c["country"] == "France" for c in data)
        names = [c["name"] for c in data]
        assert "premier_cru" in names
        assert "deuxieme_cru" in names

    @pytest.mark.asyncio
    async def test_list_classifications_filter_system(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications?system=italy_quality")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        assert all(c["system"] == "italy_quality" for c in data)
        names = [c["name"] for c in data]
        assert "docg" in names
        assert "doc" in names

    @pytest.mark.asyncio
    async def test_get_classification(self, client, seed_classifications):
        classification_id = str(seed_classifications[0].id)
        resp = await client.get(f"/api/reference/classifications/{classification_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "premier_cru"
        assert data["display_name"] == "Premier Cru Classé"

    @pytest.mark.asyncio
    async def test_get_classification_not_found(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications/000000000000000000000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_classification_invalid_id(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications/bad-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_classifications_by_system(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications/by-system")
        assert resp.status_code == 200
        data = resp.json()
        # Should have at least 2 systems: bordeaux_1855 and italy_quality
        assert len(data) >= 2
        systems = {d["system"] for d in data}
        assert "bordeaux_1855" in systems
        assert "italy_quality" in systems

    @pytest.mark.asyncio
    async def test_list_classifications_by_system_filter_country(self, client, seed_classifications):
        resp = await client.get("/api/reference/classifications/by-system?country=Italy")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        italy_system = next(d for d in data if d["system"] == "italy_quality")
        assert len(italy_system["classifications"]) >= 2


# =============================================================================
# Summary
# =============================================================================


class TestReferenceSummary:
    """Tests for the reference data summary endpoint."""

    @pytest.mark.asyncio
    async def test_summary_returns_200(self, client):
        resp = await client.get("/api/reference/summary")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_summary_with_data(
        self, client, seed_wine_types, seed_grape_varieties,
        seed_regions, seed_classifications,
    ):
        resp = await client.get("/api/reference/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["wine_types_count"] >= 3
        assert data["grape_varieties_count"] >= 4
        assert data["regions_count"] >= 5
        assert data["classifications_count"] >= 4
