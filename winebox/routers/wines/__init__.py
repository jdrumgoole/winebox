"""Wine management router package."""

from fastapi import APIRouter

from .checkin import checkin_wine, checkout_wine
from .crud import delete_all_wines, delete_wine, get_wine, list_wines, update_wine
from .grapes import get_wine_grapes, set_wine_grapes
from .scan import scan_label
from .scores import (
    add_wine_score,
    delete_wine_score,
    get_wine_scores,
    update_wine_score,
)

router = APIRouter()

# Scan endpoint
router.add_api_route("/scan", scan_label, methods=["POST"])

# Check-in/check-out endpoints
router.add_api_route(
    "/checkin",
    checkin_wine,
    methods=["POST"],
    status_code=201,
)
router.add_api_route("/{wine_id}/checkout", checkout_wine, methods=["POST"])

# CRUD endpoints - Note: /all must come before /{wine_id} to avoid conflicts
router.add_api_route("", list_wines, methods=["GET"])
router.add_api_route("/all", delete_all_wines, methods=["DELETE"])
router.add_api_route("/{wine_id}", get_wine, methods=["GET"])
router.add_api_route("/{wine_id}", update_wine, methods=["PUT"])
router.add_api_route("/{wine_id}", delete_wine, methods=["DELETE"], status_code=204)

# Grape blend endpoints
router.add_api_route("/{wine_id}/grapes", get_wine_grapes, methods=["GET"])
router.add_api_route("/{wine_id}/grapes", set_wine_grapes, methods=["POST"])

# Score endpoints
router.add_api_route("/{wine_id}/scores", get_wine_scores, methods=["GET"])
router.add_api_route("/{wine_id}/scores", add_wine_score, methods=["POST"], status_code=201)
router.add_api_route("/{wine_id}/scores/{score_id}", update_wine_score, methods=["PUT"])
router.add_api_route(
    "/{wine_id}/scores/{score_id}",
    delete_wine_score,
    methods=["DELETE"],
    status_code=204,
)

__all__ = ["router"]
