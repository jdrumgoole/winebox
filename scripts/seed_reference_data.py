#!/usr/bin/env python3
"""Seed reference data from wine-schema.yaml into the database.

This script populates the reference tables:
- wine_types
- grape_varieties
- regions (hierarchical)
- classifications

Usage:
    uv run python -m scripts.seed_reference_data
    uv run python -m scripts.seed_reference_data --database path/to/db.sqlite
    uv run python -m scripts.seed_reference_data --dry-run
"""

import argparse
import sqlite3
import uuid
from pathlib import Path

import yaml


DEFAULT_DB_PATH = "data/winebox.db"
SCHEMA_PATH = Path(__file__).parent.parent / "data" / "wine-schema.yaml"


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a database connection."""
    return sqlite3.connect(db_path)


def load_schema() -> dict:
    """Load the wine-schema.yaml file."""
    with open(SCHEMA_PATH) as f:
        return yaml.safe_load(f)


def seed_wine_types(cursor: sqlite3.Cursor, schema: dict, dry_run: bool = False) -> int:
    """Seed wine_types table from schema.

    Returns count of records inserted/updated.
    """
    types_data = schema.get("types", {})
    count = 0

    for type_id, type_info in types_data.items():
        display_name = type_id.replace("_", " ").title()
        if type_id == "rosé":
            display_name = "Rosé"

        description = type_info.get("description", "")

        if dry_run:
            print(f"  [DRY RUN] Would upsert wine_type: {type_id} - {display_name}")
        else:
            cursor.execute(
                """
                INSERT INTO wine_types (id, name, description)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description
                """,
                (type_id, display_name, description),
            )
        count += 1

    return count


def normalize_grape_name(name: str) -> str:
    """Normalize grape variety name for display."""
    # Handle special characters and formatting
    name = name.replace("_", " ")
    # Title case but preserve special chars
    parts = name.split()
    normalized = []
    for part in parts:
        # Don't capitalize single letter particles like 'd' in nero d'avola
        if len(part) == 1 and part.lower() in ["d", "de", "di"]:
            normalized.append(part.lower())
        else:
            normalized.append(part.title())
    return " ".join(normalized)


def seed_grape_varieties(cursor: sqlite3.Cursor, schema: dict, dry_run: bool = False) -> int:
    """Seed grape_varieties table from schema.

    Returns count of records inserted/updated.
    """
    grape_data = schema.get("grape_varieties", {})
    count = 0

    for color in ["red", "white"]:
        color_grapes = grape_data.get(color, {})

        # International varieties
        international = color_grapes.get("international", [])
        for grape_name in international:
            display_name = normalize_grape_name(grape_name)

            if dry_run:
                print(f"  [DRY RUN] Would upsert grape_variety: {display_name} ({color}, international)")
            else:
                # Check if exists by name
                cursor.execute("SELECT id FROM grape_varieties WHERE name = ?", (display_name,))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute(
                        """
                        UPDATE grape_varieties
                        SET color = ?, category = ?, origin_country = NULL
                        WHERE id = ?
                        """,
                        (color, "international", existing[0]),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO grape_varieties (id, name, color, category, origin_country)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (str(uuid.uuid4()), display_name, color, "international", None),
                    )
            count += 1

        # Regional varieties
        regional = color_grapes.get("regional", {})
        for region_key, grapes in regional.items():
            # Map region key to country
            country_map = {
                "france": "france",
                "italy": "italy",
                "spain": "spain",
                "portugal": "portugal",
                "germany_austria": "germany",
                "americas": "americas",
                "greece": "greece",
            }
            origin_country = country_map.get(region_key, region_key)

            for grape_name in grapes:
                display_name = normalize_grape_name(grape_name)

                if dry_run:
                    print(f"  [DRY RUN] Would upsert grape_variety: {display_name} ({color}, {origin_country})")
                else:
                    cursor.execute("SELECT id FROM grape_varieties WHERE name = ?", (display_name,))
                    existing = cursor.fetchone()

                    if existing:
                        cursor.execute(
                            """
                            UPDATE grape_varieties
                            SET color = ?, category = ?, origin_country = ?
                            WHERE id = ?
                            """,
                            (color, "regional", origin_country, existing[0]),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO grape_varieties (id, name, color, category, origin_country)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (str(uuid.uuid4()), display_name, color, "regional", origin_country),
                        )
                count += 1

    return count


def normalize_region_name(name: str) -> str:
    """Normalize region name for display."""
    name = name.replace("_", " ")
    # Handle special cases
    special_cases = {
        "côte rôtie": "Côte-Rôtie",
        "saint émilion": "Saint-Émilion",
        "saint julien": "Saint-Julien",
        "saint estèphe": "Saint-Estèphe",
        "saint joseph": "Saint-Joseph",
        "châteauneuf du pape": "Châteauneuf-du-Pape",
        "côte de nuits": "Côte de Nuits",
        "côte de beaune": "Côte de Beaune",
        "côte chalonnaise": "Côte Chalonnaise",
        "côtes du rhône": "Côtes du Rhône",
        "côtes de provence": "Côtes de Provence",
        "pouilly fumé": "Pouilly-Fumé",
        "pic saint loup": "Pic Saint-Loup",
        "crozes hermitage": "Crozes-Hermitage",
        "languedoc roussillon": "Languedoc-Roussillon",
        "alsace grand cru": "Alsace Grand Cru",
        "crémant dalsace": "Crémant d'Alsace",
        "montagne de reims": "Montagne de Reims",
        "vallée de la marne": "Vallée de la Marne",
        "côte des blancs": "Côte des Blancs",
        "barbera dasti": "Barbera d'Asti",
        "moscato dasti": "Moscato d'Asti",
        "chianti classico": "Chianti Classico",
        "brunello di montalcino": "Brunello di Montalcino",
        "vino nobile di montepulciano": "Vino Nobile di Montepulciano",
        "vernaccia di san gimignano": "Vernaccia di San Gimignano",
        "colli orientali": "Colli Orientali del Friuli",
        "cerasuolo di vittoria": "Cerasuolo di Vittoria",
        "alto adige": "Alto Adige",
        "rioja alta": "Rioja Alta",
        "rioja alavesa": "Rioja Alavesa",
        "rioja oriental": "Rioja Oriental",
        "ribera del duero": "Ribera del Duero",
        "rías baixas": "Rías Baixas",
        "vinho verde": "Vinho Verde",
        "napa valley": "Napa Valley",
        "paso robles": "Paso Robles",
        "santa barbara": "Santa Barbara",
        "central coast": "Central Coast",
        "willamette valley": "Willamette Valley",
        "dundee hills": "Dundee Hills",
        "columbia valley": "Columbia Valley",
        "walla walla": "Walla Walla",
        "finger lakes": "Finger Lakes",
        "long island": "Long Island",
        "south australia": "South Australia",
        "barossa valley": "Barossa Valley",
        "mclaren vale": "McLaren Vale",
        "adelaide hills": "Adelaide Hills",
        "clare valley": "Clare Valley",
        "yarra valley": "Yarra Valley",
        "mornington peninsula": "Mornington Peninsula",
        "western australia": "Western Australia",
        "margaret river": "Margaret River",
        "new south wales": "New South Wales",
        "hunter valley": "Hunter Valley",
        "new zealand": "New Zealand",
        "central otago": "Central Otago",
        "hawkes bay": "Hawke's Bay",
        "south america": "South America",
        "maipo valley": "Maipo Valley",
        "south africa": "South Africa",
        "united states": "United States",
    }

    lower_name = name.lower()
    if lower_name in special_cases:
        return special_cases[lower_name]

    return name.title()


def seed_regions(cursor: sqlite3.Cursor, schema: dict, dry_run: bool = False) -> int:
    """Seed regions table hierarchically from schema.

    Returns count of records inserted/updated.
    """
    regions_data = schema.get("regions", {})
    count = 0
    region_ids = {}  # Map of (country, name) -> id for parent lookups

    def process_region(
        name: str,
        parent_id: str | None,
        country: str,
        level: int,
        children: dict | list | None,
    ) -> None:
        nonlocal count

        display_name = normalize_region_name(name)
        region_key = (country, name)

        if dry_run:
            parent_info = f" (parent: {parent_id[:8]}...)" if parent_id else ""
            print(f"  [DRY RUN] Would upsert region: {display_name} (level {level}){parent_info}")
            region_id = str(uuid.uuid4())
        else:
            # Check if region exists by name and country
            cursor.execute(
                "SELECT id FROM regions WHERE name = ? AND country = ?",
                (name, country),
            )
            existing = cursor.fetchone()

            if existing:
                region_id = existing[0]
                cursor.execute(
                    """
                    UPDATE regions
                    SET display_name = ?, parent_id = ?, level = ?
                    WHERE id = ?
                    """,
                    (display_name, parent_id, level, region_id),
                )
            else:
                region_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO regions (id, name, display_name, parent_id, country, level)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (region_id, name, display_name, parent_id, country, level),
                )

        region_ids[region_key] = region_id
        count += 1

        # Process children
        if isinstance(children, dict):
            for child_name, grandchildren in children.items():
                process_region(child_name, region_id, country, level + 1, grandchildren)
        elif isinstance(children, list):
            for child_name in children:
                process_region(child_name, region_id, country, level + 1, None)

    # Process each country
    for country_name, country_regions in regions_data.items():
        # Create country entry (level 0)
        country_display = normalize_region_name(country_name)

        if dry_run:
            print(f"  [DRY RUN] Would upsert country: {country_display} (level 0)")
            country_id = str(uuid.uuid4())
        else:
            cursor.execute(
                "SELECT id FROM regions WHERE name = ? AND level = 0",
                (country_name,),
            )
            existing = cursor.fetchone()

            if existing:
                country_id = existing[0]
                cursor.execute(
                    """
                    UPDATE regions
                    SET display_name = ?, country = ?
                    WHERE id = ?
                    """,
                    (country_display, country_name, country_id),
                )
            else:
                country_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO regions (id, name, display_name, parent_id, country, level)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (country_id, country_name, country_display, None, country_name, 0),
                )

        region_ids[(country_name, country_name)] = country_id
        count += 1

        # Process country's regions
        if isinstance(country_regions, dict):
            for region_name, subregions in country_regions.items():
                process_region(region_name, country_id, country_name, 1, subregions)
        elif isinstance(country_regions, list):
            for region_name in country_regions:
                process_region(region_name, country_id, country_name, 1, None)

    return count


def seed_classifications(cursor: sqlite3.Cursor, schema: dict, dry_run: bool = False) -> int:
    """Seed classifications table from schema.

    Returns count of records inserted/updated.
    """
    classifications_data = schema.get("classifications", {})
    count = 0

    def normalize_classification_name(name: str) -> str:
        """Normalize classification name for display."""
        name = name.replace("_", " ")
        # Handle special cases
        special_cases = {
            "aoc aop": "AOC/AOP",
            "igp": "IGP",
            "vin de france": "Vin de France",
            "grand cru": "Grand Cru",
            "premier cru": "Premier Cru",
            "premier cru classé": "Premier Cru Classé",
            "deuxième cru classé": "Deuxième Cru Classé",
            "troisième cru classé": "Troisième Cru Classé",
            "quatrième cru classé": "Quatrième Cru Classé",
            "cinquième cru classé": "Cinquième Cru Classé",
            "cru bourgeois": "Cru Bourgeois",
            "docg": "DOCG",
            "doc": "DOC",
            "igt": "IGT",
            "vino": "Vino",
            "dop": "DOP",
            "do": "DO",
            "vino de pago": "Vino de Pago",
            "grosses gewächs": "Grosses Gewächs",
            "erstes gewächs": "Erstes Gewächs",
            "ortswein": "Ortswein",
            "gutswein": "Gutswein",
            "ava": "AVA",
            "estate bottled": "Estate Bottled",
            "reserve": "Reserve",
            "gi": "GI",
            "kabinett": "Kabinett",
            "spätlese": "Spätlese",
            "auslese": "Auslese",
            "beerenauslese": "Beerenauslese",
            "trockenbeerenauslese": "Trockenbeerenauslese",
            "eiswein": "Eiswein",
            "joven": "Joven",
            "crianza": "Crianza",
            "reserva": "Reserva",
            "gran reserva": "Gran Reserva",
        }
        lower_name = name.lower()
        if lower_name in special_cases:
            return special_cases[lower_name]
        return name.title()

    def process_classification(
        name: str,
        country: str,
        system: str,
        level: int | None = None,
    ) -> None:
        nonlocal count
        display_name = normalize_classification_name(name)

        if dry_run:
            level_info = f" (level {level})" if level is not None else ""
            print(f"  [DRY RUN] Would upsert classification: {display_name} - {system}{level_info}")
        else:
            # Check if exists by name and system
            cursor.execute(
                "SELECT id FROM classifications WHERE name = ? AND system = ?",
                (name, system),
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE classifications
                    SET display_name = ?, country = ?, level = ?
                    WHERE id = ?
                    """,
                    (display_name, country, level, existing[0]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO classifications (id, name, display_name, country, system, level)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), name, display_name, country, system, level),
                )
        count += 1

    for country, country_classifications in classifications_data.items():
        if isinstance(country_classifications, list):
            # Simple list of classifications
            for name in country_classifications:
                process_classification(name, country, f"{country}_general")
        elif isinstance(country_classifications, dict):
            # May have sub-systems
            for key, value in country_classifications.items():
                if isinstance(value, list):
                    # This is a classification system
                    for i, name in enumerate(value, 1):
                        process_classification(name, country, key, level=i)
                elif isinstance(value, dict):
                    # Nested system (e.g., prädikat, vdp)
                    for i, name in enumerate(value, 1):
                        process_classification(name, country, key, level=i)
                else:
                    # Single value
                    process_classification(key, country, f"{country}_general")

    return count


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Seed reference data from wine-schema.yaml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--database",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without applying changes",
    )

    args = parser.parse_args()

    db_path = Path(args.database)
    if not db_path.exists():
        print(f"Database not found at: {db_path}")
        print("Run the application first to create the database, then run migrations.")
        return 1

    if not SCHEMA_PATH.exists():
        print(f"Schema file not found at: {SCHEMA_PATH}")
        return 1

    print(f"Loading schema from: {SCHEMA_PATH}")
    schema = load_schema()

    print(f"Connecting to database: {db_path}")
    conn = get_connection(str(db_path))
    cursor = conn.cursor()

    try:
        print()
        print("Seeding wine_types...")
        type_count = seed_wine_types(cursor, schema, args.dry_run)
        print(f"  Processed {type_count} wine types")

        print()
        print("Seeding grape_varieties...")
        grape_count = seed_grape_varieties(cursor, schema, args.dry_run)
        print(f"  Processed {grape_count} grape varieties")

        print()
        print("Seeding regions...")
        region_count = seed_regions(cursor, schema, args.dry_run)
        print(f"  Processed {region_count} regions")

        print()
        print("Seeding classifications...")
        class_count = seed_classifications(cursor, schema, args.dry_run)
        print(f"  Processed {class_count} classifications")

        if not args.dry_run:
            conn.commit()
            print()
            print("All reference data seeded successfully!")
        else:
            print()
            print("[DRY RUN] No changes were made to the database.")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
