#!/usr/bin/env python3
"""Drop the old wines text index so Beanie can create the updated one.

The text index was expanded in v0.5.12 to include sub_region and appellation.
MongoDB does not allow creating a new text index when one already exists with
different fields, so the old index must be dropped first.

Usage:
    python scripts/migrations/drop_old_text_index.py [MONGODB_URL]

If MONGODB_URL is not provided, falls back to WINEBOX_MONGODB_URL env var,
then defaults to mongodb://localhost:27017.
"""

import os
import sys

from pymongo import MongoClient
from pymongo.errors import OperationFailure


OLD_INDEX_NAME = (
    "name_text_winery_text_region_text_country_text_front_label_text_text"
)


def main() -> None:
    """Drop the old text index from the wines collection."""
    mongo_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("WINEBOX_MONGODB_URL", "mongodb://localhost:27017")
    )

    # Extract database name from URL, default to 'winebox'
    db_name = "winebox"
    if "/" in mongo_url.split("://", 1)[-1]:
        path = mongo_url.split("://", 1)[-1].split("/", 1)
        if len(path) > 1:
            candidate = path[1].split("?")[0]
            if candidate:
                db_name = candidate

    client = MongoClient(mongo_url)
    db = client[db_name]
    collection = db["wines"]

    # List current indexes
    indexes = {idx["name"]: idx for idx in collection.list_indexes()}

    if OLD_INDEX_NAME in indexes:
        try:
            collection.drop_index(OLD_INDEX_NAME)
            print(f"Dropped old text index: {OLD_INDEX_NAME}")
        except OperationFailure as e:
            print(f"Failed to drop index: {e}")
            sys.exit(1)
    else:
        print(f"Old text index not found (already dropped or never existed)")

    # Verify
    remaining = [idx["name"] for idx in collection.list_indexes()]
    print(f"Remaining indexes: {remaining}")

    client.close()


if __name__ == "__main__":
    main()
