"""Admin panel endpoints for user management and statistics."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pathlib import Path
from slowapi import Limiter
from slowapi.util import get_remote_address

from winebox.models import User, Wine
from winebox.services.auth import RequireAdmin

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("", response_model=None)
async def admin_panel() -> FileResponse:
    """Serve the admin panel HTML page.

    Auth is not checked here because the token lives in localStorage and is not
    sent on full-page navigation. The admin page (admin.js) reads the token,
    calls /admin/api/* with it, and redirects to login if missing or 401/403.
    """
    static_path = Path(__file__).parent.parent / "static" / "admin.html"
    return FileResponse(static_path, media_type="text/html")


@router.get("/api/users")
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    admin: RequireAdmin,
) -> dict[str, Any]:
    """List all users with their cellar statistics.

    Returns user information including:
    - Basic user info (email, verification status, etc.)
    - Account timestamps (created_at, last_login)
    - Cellar size (total bottles)
    """
    # Get all users
    users = await User.find_all().sort([("created_at", -1)]).to_list()

    # Get cellar sizes via aggregation
    cellar_sizes_pipeline = [
        {"$match": {"inventory.quantity": {"$gt": 0}}},
        {"$group": {"_id": "$owner_id", "total": {"$sum": "$inventory.quantity"}}},
    ]
    cursor = await Wine.get_pymongo_collection().aggregate(
        cellar_sizes_pipeline
    )
    cellar_sizes_result = await cursor.to_list(length=None)

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
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/stats")
@limiter.limit("30/minute")
async def get_admin_stats(
    request: Request,
    admin: RequireAdmin,
) -> dict[str, Any]:
    """Get overall system statistics for the admin panel.

    Returns:
    - Total users (active, verified, admins)
    - Total wines across all users
    - Total bottles across all users
    """
    # User counts — single $facet instead of 4 separate counts
    user_cursor = await User.get_pymongo_collection().aggregate([
        {"$facet": {
            "total": [{"$count": "count"}],
            "active": [{"$match": {"is_active": True}}, {"$count": "count"}],
            "verified": [{"$match": {"is_verified": True}}, {"$count": "count"}],
            "admins": [{"$match": {"is_superuser": True}}, {"$count": "count"}],
        }},
    ])
    user_result = await user_cursor.to_list(length=None)
    uf = user_result[0] if user_result else {}
    total_users = uf.get("total", [{}])[0].get("count", 0) if uf.get("total") else 0
    active_users = uf.get("active", [{}])[0].get("count", 0) if uf.get("active") else 0
    verified_users = uf.get("verified", [{}])[0].get("count", 0) if uf.get("verified") else 0
    admin_users = uf.get("admins", [{}])[0].get("count", 0) if uf.get("admins") else 0

    # Wine counts — single $facet instead of 2 counts + 1 aggregation
    wine_cursor = await Wine.get_pymongo_collection().aggregate([
        {"$facet": {
            "total": [{"$count": "count"}],
            "in_stock": [{"$match": {"inventory.quantity": {"$gt": 0}}}, {"$count": "count"}],
            "total_bottles": [
                {"$match": {"inventory.quantity": {"$gt": 0}}},
                {"$group": {"_id": None, "total": {"$sum": "$inventory.quantity"}}},
            ],
        }},
    ])
    wine_result = await wine_cursor.to_list(length=None)
    wf = wine_result[0] if wine_result else {}
    total_wines = wf.get("total", [{}])[0].get("count", 0) if wf.get("total") else 0
    wines_in_stock = wf.get("in_stock", [{}])[0].get("count", 0) if wf.get("in_stock") else 0
    total_bottles = wf.get("total_bottles", [{}])[0].get("total", 0) if wf.get("total_bottles") else 0

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
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
