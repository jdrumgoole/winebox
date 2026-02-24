"""Admin panel endpoints for user management and statistics."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path

from winebox.models import User, Wine
from winebox.services.auth import RequireAdmin

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def admin_panel() -> FileResponse:
    """Serve the admin panel HTML page.

    Note: The page itself doesn't require authentication - the JavaScript
    will check auth and redirect if needed. The API endpoints still require
    admin privileges.
    """
    static_path = Path(__file__).parent.parent / "static" / "admin.html"
    return FileResponse(static_path, media_type="text/html")


@router.get("/api/users")
async def list_users(
    admin: RequireAdmin,
) -> dict[str, Any]:
    """List all users with their cellar statistics.

    Returns user information including:
    - Basic user info (email, verification status, etc.)
    - Account timestamps (created_at, last_login)
    - Cellar size (total bottles)
    """
    # Get all users
    users = await User.find_all().sort(-User.created_at).to_list()

    # Get cellar sizes via aggregation
    cellar_sizes_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}}},
        {"$group": {"_id": "$owner_id", "total": {"$sum": "$inventory.quantity"}}},
    ]
    cellar_sizes_result = await Wine.get_pymongo_collection().aggregate(
        cellar_sizes_pipeline
    ).to_list(length=None)

    # Create a lookup dict for cellar sizes
    cellar_size_by_user = {
        row["_id"]: row["total"] for row in cellar_sizes_result
    }

    # Build response
    user_list = []
    for user in users:
        user_data = {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "cellar_size": cellar_size_by_user.get(user.id, 0),
        }
        user_list.append(user_data)

    return {
        "users": user_list,
        "total_users": len(users),
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/api/stats")
async def get_admin_stats(
    admin: RequireAdmin,
) -> dict[str, Any]:
    """Get overall system statistics for the admin panel.

    Returns:
    - Total users (active, verified, admins)
    - Total wines across all users
    - Total bottles across all users
    """
    # User counts
    total_users = await User.count()
    active_users = await User.find(User.is_active == True).count()
    verified_users = await User.find(User.is_verified == True).count()
    admin_users = await User.find(User.is_superuser == True).count()

    # Wine counts
    total_wines = await Wine.count()
    wines_in_stock = await Wine.find(Wine.inventory.quantity > 0).count()

    # Total bottles via aggregation
    total_bottles_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}}},
        {"$group": {"_id": None, "total": {"$sum": "$inventory.quantity"}}},
    ]
    total_bottles_result = await Wine.get_pymongo_collection().aggregate(
        total_bottles_pipeline
    ).to_list(length=None)
    total_bottles = total_bottles_result[0]["total"] if total_bottles_result else 0

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "verified": verified_users,
            "admins": admin_users,
        },
        "wines": {
            "total": total_wines,
            "in_stock": wines_in_stock,
            "total_bottles": total_bottles,
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
