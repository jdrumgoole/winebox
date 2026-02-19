#!/usr/bin/env python3
"""Migrate WineBox data from SQLite to MongoDB.

This script migrates all data from the SQLite database to MongoDB:
1. Users (with ID mapping)
2. Reference data (wine types, grapes, regions, classifications)
3. Wines (with embedded inventory, grapes, scores)
4. Transactions (with wine_id mapping)
5. X-Wines data

Usage:
    uv run python scripts/migrations/migrate_sqlite_to_mongo.py

Environment variables:
    WINEBOX_MONGODB_URL: MongoDB connection URL (default: mongodb://localhost:27017)
    WINEBOX_MONGODB_DATABASE: MongoDB database name (default: winebox)
    WINEBOX_SQLITE_PATH: Path to SQLite database (default: data/winebox.db)
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def migrate():
    """Run the migration from SQLite to MongoDB."""
    import uuid as uuid_module

    from beanie import PydanticObjectId, init_beanie
    from motor.motor_asyncio import AsyncIOMotorClient
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import selectinload

    # Import SQLAlchemy models (need to import the old schema)
    # We'll create minimal SQLAlchemy models for reading
    from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
    from sqlalchemy.orm import DeclarativeBase, relationship
    import enum

    class Base(DeclarativeBase):
        pass

    class TransactionTypeSQLite(str, enum.Enum):
        CHECK_IN = "CHECK_IN"
        CHECK_OUT = "CHECK_OUT"

    # Define minimal SQLAlchemy models for reading existing data
    class UserSQLite(Base):
        __tablename__ = "user"
        id = Column(String(36), primary_key=True)
        username = Column(String(50), unique=True, nullable=False)
        email = Column(String(255), unique=True, nullable=False)
        hashed_password = Column(String(255), nullable=False)
        full_name = Column(String(100))
        anthropic_api_key = Column(String(255))
        is_active = Column(Boolean, default=True)
        is_verified = Column(Boolean, default=False)
        is_superuser = Column(Boolean, default=False)
        created_at = Column(DateTime)
        updated_at = Column(DateTime)
        last_login = Column(DateTime)

    class WineSQLite(Base):
        __tablename__ = "wines"
        id = Column(String(36), primary_key=True)
        name = Column(String(255), nullable=False)
        winery = Column(String(255))
        vintage = Column(Integer)
        grape_variety = Column(String(255))
        region = Column(String(255))
        country = Column(String(255))
        alcohol_percentage = Column(Float)
        front_label_text = Column(Text, default="")
        back_label_text = Column(Text)
        front_label_image_path = Column(String(500))
        back_label_image_path = Column(String(500))
        wine_type_id = Column(String(36))
        wine_subtype = Column(String(50))
        appellation_id = Column(String(36))
        classification_id = Column(String(36))
        price_tier = Column(String(50))
        drink_window_start = Column(Integer)
        drink_window_end = Column(Integer)
        producer_type = Column(String(50))
        created_at = Column(DateTime)
        updated_at = Column(DateTime)

    class CellarInventorySQLite(Base):
        __tablename__ = "cellar_inventory"
        id = Column(String(36), primary_key=True)
        wine_id = Column(String(36), ForeignKey("wines.id"))
        quantity = Column(Integer, default=0)
        updated_at = Column(DateTime)

    class TransactionSQLite(Base):
        __tablename__ = "transactions"
        id = Column(String(36), primary_key=True)
        wine_id = Column(String(36), ForeignKey("wines.id"))
        transaction_type = Column(Enum(TransactionTypeSQLite))
        quantity = Column(Integer)
        notes = Column(Text)
        transaction_date = Column(DateTime)
        created_at = Column(DateTime)

    class WineTypeSQLite(Base):
        __tablename__ = "wine_types"
        id = Column(String(36), primary_key=True)
        name = Column(String(50))
        description = Column(Text)

    class GrapeVarietySQLite(Base):
        __tablename__ = "grape_varieties"
        id = Column(String(36), primary_key=True)
        name = Column(String(100))
        color = Column(String(10))
        category = Column(String(50))
        origin_country = Column(String(100))

    class RegionSQLite(Base):
        __tablename__ = "regions"
        id = Column(String(36), primary_key=True)
        name = Column(String(100))
        display_name = Column(String(150))
        level = Column(Integer)
        parent_id = Column(String(36))
        country = Column(String(100))

    class ClassificationSQLite(Base):
        __tablename__ = "classifications"
        id = Column(String(36), primary_key=True)
        name = Column(String(100))
        display_name = Column(String(150))
        country = Column(String(100))
        system = Column(String(100))
        level = Column(Integer)

    class WineGrapeSQLite(Base):
        __tablename__ = "wine_grapes"
        id = Column(String(36), primary_key=True)
        wine_id = Column(String(36), ForeignKey("wines.id"))
        grape_variety_id = Column(String(36), ForeignKey("grape_varieties.id"))
        percentage = Column(Float)

    class WineScoreSQLite(Base):
        __tablename__ = "wine_scores"
        id = Column(String(36), primary_key=True)
        wine_id = Column(String(36), ForeignKey("wines.id"))
        source = Column(String(100))
        score = Column(Integer)
        score_type = Column(String(20))
        review_date = Column(DateTime)
        reviewer = Column(String(100))
        notes = Column(Text)
        created_at = Column(DateTime)

    class XWinesWineSQLite(Base):
        __tablename__ = "xwines_wines"
        id = Column(Integer, primary_key=True)
        name = Column(String(500))
        wine_type = Column(String(50))
        elaborate = Column(Text)
        grapes = Column(Text)
        harmonize = Column(Text)
        abv = Column(Float)
        body = Column(String(50))
        acidity = Column(String(50))
        country_code = Column(String(10))
        country = Column(String(100))
        region_id = Column(Integer)
        region_name = Column(String(200))
        winery_id = Column(Integer)
        winery_name = Column(String(300))
        website = Column(String(500))
        vintages = Column(Text)
        avg_rating = Column(Float)
        rating_count = Column(Integer, default=0)

    class XWinesMetadataSQLite(Base):
        __tablename__ = "xwines_metadata"
        key = Column(String(100), primary_key=True)
        value = Column(Text)

    # Import MongoDB models
    from winebox.models import (
        Classification,
        GrapeBlendEntry,
        GrapeVariety,
        InventoryInfo,
        Region,
        ScoreEntry,
        Transaction,
        TransactionType,
        User,
        Wine,
        WineType,
        XWinesMetadata,
        XWinesWine,
    )

    # Configuration
    sqlite_path = os.environ.get("WINEBOX_SQLITE_PATH", "data/winebox.db")
    mongodb_url = os.environ.get("WINEBOX_MONGODB_URL", "mongodb://localhost:27017")
    mongodb_database = os.environ.get("WINEBOX_MONGODB_DATABASE", "winebox")

    print(f"SQLite path: {sqlite_path}")
    print(f"MongoDB URL: {mongodb_url}")
    print(f"MongoDB database: {mongodb_database}")

    # Check if SQLite database exists
    if not Path(sqlite_path).exists():
        print(f"ERROR: SQLite database not found at {sqlite_path}")
        sys.exit(1)

    # Connect to SQLite
    sqlite_url = f"sqlite+aiosqlite:///{sqlite_path}"
    engine = create_async_engine(sqlite_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Connect to MongoDB
    mongo_client = AsyncIOMotorClient(mongodb_url)
    mongo_db = mongo_client[mongodb_database]

    # Initialize Beanie
    await init_beanie(
        database=mongo_db,
        document_models=[
            User, Wine, Transaction, WineType, GrapeVariety, Region,
            Classification, XWinesWine, XWinesMetadata
        ]
    )

    # Tracking for ID mapping
    user_id_map: dict[str, PydanticObjectId] = {}
    wine_id_map: dict[str, PydanticObjectId] = {}
    grape_id_map: dict[str, PydanticObjectId] = {}
    region_id_map: dict[str, PydanticObjectId] = {}
    classification_id_map: dict[str, PydanticObjectId] = {}

    async with async_session() as session:
        # =========================================================================
        # 1. Migrate Users
        # =========================================================================
        print("\n=== Migrating Users ===")
        result = await session.execute(select(UserSQLite))
        users_sqlite = result.scalars().all()
        print(f"Found {len(users_sqlite)} users in SQLite")

        for u in users_sqlite:
            user = User(
                username=u.username,
                email=u.email,
                hashed_password=u.hashed_password,
                full_name=u.full_name,
                anthropic_api_key=u.anthropic_api_key,
                is_active=u.is_active if u.is_active is not None else True,
                is_verified=u.is_verified if u.is_verified is not None else False,
                is_superuser=u.is_superuser if u.is_superuser is not None else False,
                created_at=u.created_at or datetime.utcnow(),
                updated_at=u.updated_at or datetime.utcnow(),
                last_login=u.last_login,
            )
            await user.insert()
            user_id_map[u.id] = user.id
            print(f"  Migrated user: {u.username}")

        # =========================================================================
        # 2. Migrate Wine Types
        # =========================================================================
        print("\n=== Migrating Wine Types ===")
        result = await session.execute(select(WineTypeSQLite))
        wine_types_sqlite = result.scalars().all()
        print(f"Found {len(wine_types_sqlite)} wine types in SQLite")

        for wt in wine_types_sqlite:
            wine_type = WineType(
                type_id=wt.id,  # Use original ID as type_id
                name=wt.name,
                description=wt.description,
            )
            await wine_type.insert()
            print(f"  Migrated wine type: {wt.name}")

        # =========================================================================
        # 3. Migrate Grape Varieties
        # =========================================================================
        print("\n=== Migrating Grape Varieties ===")
        result = await session.execute(select(GrapeVarietySQLite))
        grapes_sqlite = result.scalars().all()
        print(f"Found {len(grapes_sqlite)} grape varieties in SQLite")

        for g in grapes_sqlite:
            grape = GrapeVariety(
                name=g.name,
                color=g.color,
                category=g.category,
                origin_country=g.origin_country,
            )
            await grape.insert()
            grape_id_map[g.id] = grape.id
            print(f"  Migrated grape: {g.name}")

        # =========================================================================
        # 4. Migrate Regions
        # =========================================================================
        print("\n=== Migrating Regions ===")
        result = await session.execute(select(RegionSQLite))
        regions_sqlite = result.scalars().all()
        print(f"Found {len(regions_sqlite)} regions in SQLite")

        # First pass: create all regions without parent references
        for r in regions_sqlite:
            region = Region(
                name=r.name,
                display_name=r.display_name,
                level=r.level,
                country=r.country,
                parent_id=None,  # Set in second pass
                path=r.name.lower().replace(" ", "_"),
            )
            await region.insert()
            region_id_map[r.id] = region.id
            print(f"  Migrated region: {r.display_name}")

        # Second pass: update parent references
        for r in regions_sqlite:
            if r.parent_id and r.parent_id in region_id_map:
                region = await Region.get(region_id_map[r.id])
                if region:
                    region.parent_id = region_id_map[r.parent_id]
                    await region.save()

        # =========================================================================
        # 5. Migrate Classifications
        # =========================================================================
        print("\n=== Migrating Classifications ===")
        result = await session.execute(select(ClassificationSQLite))
        classifications_sqlite = result.scalars().all()
        print(f"Found {len(classifications_sqlite)} classifications in SQLite")

        for c in classifications_sqlite:
            classification = Classification(
                name=c.name,
                display_name=c.display_name,
                country=c.country,
                system=c.system,
                level=c.level,
            )
            await classification.insert()
            classification_id_map[c.id] = classification.id
            print(f"  Migrated classification: {c.display_name}")

        # =========================================================================
        # 6. Migrate Wines with embedded data
        # =========================================================================
        print("\n=== Migrating Wines ===")
        result = await session.execute(select(WineSQLite))
        wines_sqlite = result.scalars().all()
        print(f"Found {len(wines_sqlite)} wines in SQLite")

        for w in wines_sqlite:
            # Get inventory
            inv_result = await session.execute(
                select(CellarInventorySQLite).where(CellarInventorySQLite.wine_id == w.id)
            )
            inventory_sqlite = inv_result.scalar_one_or_none()

            inventory = InventoryInfo(
                quantity=inventory_sqlite.quantity if inventory_sqlite else 0,
                updated_at=inventory_sqlite.updated_at if inventory_sqlite else datetime.utcnow(),
            )

            # Get grape blends
            grape_result = await session.execute(
                select(WineGrapeSQLite).where(WineGrapeSQLite.wine_id == w.id)
            )
            grapes_sqlite_for_wine = grape_result.scalars().all()

            grape_blends = []
            for wg in grapes_sqlite_for_wine:
                if wg.grape_variety_id in grape_id_map:
                    # Get grape name from SQLite
                    grape_query = await session.execute(
                        select(GrapeVarietySQLite).where(GrapeVarietySQLite.id == wg.grape_variety_id)
                    )
                    grape_sqlite = grape_query.scalar_one_or_none()
                    if grape_sqlite:
                        grape_blends.append(GrapeBlendEntry(
                            grape_variety_id=str(grape_id_map[wg.grape_variety_id]),
                            grape_name=grape_sqlite.name,
                            percentage=wg.percentage,
                            color=grape_sqlite.color,
                        ))

            # Get scores
            score_result = await session.execute(
                select(WineScoreSQLite).where(WineScoreSQLite.wine_id == w.id)
            )
            scores_sqlite = score_result.scalars().all()

            scores = []
            for s in scores_sqlite:
                scores.append(ScoreEntry(
                    id=s.id,
                    source=s.source,
                    score=s.score,
                    score_type=s.score_type,
                    review_date=s.review_date,
                    reviewer=s.reviewer,
                    notes=s.notes,
                    created_at=s.created_at or datetime.utcnow(),
                ))

            # Create wine
            wine = Wine(
                name=w.name,
                winery=w.winery,
                vintage=w.vintage,
                grape_variety=w.grape_variety,
                region=w.region,
                country=w.country,
                alcohol_percentage=w.alcohol_percentage,
                front_label_text=w.front_label_text or "",
                back_label_text=w.back_label_text,
                front_label_image_path=w.front_label_image_path,
                back_label_image_path=w.back_label_image_path,
                wine_type_id=w.wine_type_id,
                wine_subtype=w.wine_subtype,
                appellation_id=w.appellation_id,
                classification_id=w.classification_id,
                price_tier=w.price_tier,
                drink_window_start=w.drink_window_start,
                drink_window_end=w.drink_window_end,
                producer_type=w.producer_type,
                created_at=w.created_at or datetime.utcnow(),
                updated_at=w.updated_at or datetime.utcnow(),
                inventory=inventory,
                grape_blends=grape_blends,
                scores=scores,
            )
            await wine.insert()
            wine_id_map[w.id] = wine.id
            print(f"  Migrated wine: {w.name} ({w.vintage or 'NV'})")

        # =========================================================================
        # 7. Migrate Transactions
        # =========================================================================
        print("\n=== Migrating Transactions ===")
        result = await session.execute(select(TransactionSQLite))
        transactions_sqlite = result.scalars().all()
        print(f"Found {len(transactions_sqlite)} transactions in SQLite")

        for t in transactions_sqlite:
            if t.wine_id in wine_id_map:
                transaction = Transaction(
                    wine_id=wine_id_map[t.wine_id],
                    transaction_type=TransactionType(t.transaction_type.value),
                    quantity=t.quantity,
                    notes=t.notes,
                    transaction_date=t.transaction_date or datetime.utcnow(),
                    created_at=t.created_at or datetime.utcnow(),
                )
                await transaction.insert()
                print(f"  Migrated transaction: {t.transaction_type.value} x{t.quantity}")
            else:
                print(f"  WARNING: Skipped transaction for missing wine_id: {t.wine_id}")

        # =========================================================================
        # 8. Migrate X-Wines Data
        # =========================================================================
        print("\n=== Migrating X-Wines Data ===")
        result = await session.execute(select(XWinesWineSQLite))
        xwines_sqlite = result.scalars().all()
        print(f"Found {len(xwines_sqlite)} X-Wines records in SQLite")

        batch_size = 1000
        for i in range(0, len(xwines_sqlite), batch_size):
            batch = xwines_sqlite[i:i+batch_size]
            xwines_docs = []
            for xw in batch:
                xwines_docs.append(XWinesWine(
                    xwines_id=xw.id,
                    name=xw.name,
                    wine_type=xw.wine_type,
                    elaborate=xw.elaborate,
                    grapes=xw.grapes,
                    harmonize=xw.harmonize,
                    abv=xw.abv,
                    body=xw.body,
                    acidity=xw.acidity,
                    country_code=xw.country_code,
                    country=xw.country,
                    region_id=xw.region_id,
                    region_name=xw.region_name,
                    winery_id=xw.winery_id,
                    winery_name=xw.winery_name,
                    website=xw.website,
                    vintages=xw.vintages,
                    avg_rating=xw.avg_rating,
                    rating_count=xw.rating_count or 0,
                ))
            await XWinesWine.insert_many(xwines_docs)
            print(f"  Migrated X-Wines batch {i//batch_size + 1}: {len(batch)} records")

        # Migrate X-Wines metadata
        result = await session.execute(select(XWinesMetadataSQLite))
        xwines_metadata_sqlite = result.scalars().all()
        print(f"Found {len(xwines_metadata_sqlite)} X-Wines metadata records in SQLite")

        for m in xwines_metadata_sqlite:
            metadata = XWinesMetadata(
                key=m.key,
                value=m.value,
            )
            await metadata.insert()
            print(f"  Migrated X-Wines metadata: {m.key}")

    # =========================================================================
    # Verify Migration
    # =========================================================================
    print("\n=== Verification ===")
    user_count = await User.count()
    wine_count = await Wine.count()
    transaction_count = await Transaction.count()
    xwines_count = await XWinesWine.count()
    grape_count = await GrapeVariety.count()
    region_count = await Region.count()
    classification_count = await Classification.count()

    print(f"Users in MongoDB: {user_count}")
    print(f"Wines in MongoDB: {wine_count}")
    print(f"Transactions in MongoDB: {transaction_count}")
    print(f"X-Wines records in MongoDB: {xwines_count}")
    print(f"Grape Varieties in MongoDB: {grape_count}")
    print(f"Regions in MongoDB: {region_count}")
    print(f"Classifications in MongoDB: {classification_count}")

    print("\n=== Migration Complete ===")

    # Cleanup
    mongo_client.close()
    await engine.dispose()


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Migrate WineBox from SQLite to MongoDB")
    parser.add_argument(
        "--sqlite-path",
        help="Path to SQLite database (default: data/winebox.db)",
        default=None,
    )
    parser.add_argument(
        "--mongodb-url",
        help="MongoDB connection URL (default: mongodb://localhost:27017)",
        default=None,
    )
    parser.add_argument(
        "--mongodb-database",
        help="MongoDB database name (default: winebox)",
        default=None,
    )
    args = parser.parse_args()

    if args.sqlite_path:
        os.environ["WINEBOX_SQLITE_PATH"] = args.sqlite_path
    if args.mongodb_url:
        os.environ["WINEBOX_MONGODB_URL"] = args.mongodb_url
    if args.mongodb_database:
        os.environ["WINEBOX_MONGODB_DATABASE"] = args.mongodb_database

    asyncio.run(migrate())


if __name__ == "__main__":
    main()
