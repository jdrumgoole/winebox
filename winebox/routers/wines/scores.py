"""Wine score/rating endpoints."""

import logging
import uuid
from datetime import datetime, timezone

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pydantic import ValidationError

from winebox.models import ScoreEntry, Wine
from winebox.schemas.reference import (
    WineScoreCreate,
    WineScoreResponse,
    WineScoresResponse,
    WineScoreUpdate,
)
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)


async def get_wine_scores(
    wine_id: str,
    current_user: RequireAuth,
) -> WineScoresResponse:
    """Get all scores for a wine."""
    # Verify wine exists and belongs to current user
    try:
        wine = await Wine.find_one(
            Wine.id == PydanticObjectId(wine_id),
            Wine.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Build response from embedded scores
    scores_response = []
    for score in wine.scores:
        scores_response.append(WineScoreResponse(
            id=score.id,
            wine_id=wine_id,
            source=score.source,
            score=score.score,
            score_type=score.score_type,
            review_date=score.review_date,
            reviewer=score.reviewer,
            notes=score.notes,
            created_at=score.created_at,
            normalized_score=score.normalized_score,
        ))

    # Calculate average normalized score
    average_score = None
    if wine.scores:
        normalized_scores = [s.normalized_score for s in wine.scores]
        average_score = sum(normalized_scores) / len(normalized_scores)

    return WineScoresResponse(
        wine_id=wine_id,
        scores=scores_response,
        average_score=average_score,
    )


async def add_wine_score(
    wine_id: str,
    current_user: RequireAuth,
    score_data: WineScoreCreate,
) -> WineScoreResponse:
    """Add a score/rating for a wine."""
    # Verify wine exists and belongs to current user
    try:
        wine = await Wine.find_one(
            Wine.id == PydanticObjectId(wine_id),
            Wine.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Validate score type
    valid_score_types = ["100_point", "20_point", "5_star"]
    if score_data.score_type not in valid_score_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid score_type. Must be one of: {valid_score_types}",
        )

    # Create score entry
    score = ScoreEntry(
        id=str(uuid.uuid4()),
        source=score_data.source,
        score=score_data.score,
        score_type=score_data.score_type,
        review_date=score_data.review_date,
        reviewer=score_data.reviewer,
        notes=score_data.notes,
        created_at=datetime.now(timezone.utc),
    )

    # Add to wine's scores
    wine.scores.append(score)
    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()

    return WineScoreResponse(
        id=score.id,
        wine_id=wine_id,
        source=score.source,
        score=score.score,
        score_type=score.score_type,
        review_date=score.review_date,
        reviewer=score.reviewer,
        notes=score.notes,
        created_at=score.created_at,
        normalized_score=score.normalized_score,
    )


async def update_wine_score(
    wine_id: str,
    score_id: str,
    current_user: RequireAuth,
    score_update: WineScoreUpdate,
) -> WineScoreResponse:
    """Update a score for a wine."""
    # Get wine - must belong to current user
    try:
        wine = await Wine.find_one(
            Wine.id == PydanticObjectId(wine_id),
            Wine.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Find score
    score_index = None
    for i, s in enumerate(wine.scores):
        if s.id == score_id:
            score_index = i
            break

    if score_index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Score with ID {score_id} not found for wine {wine_id}",
        )

    # Update fields
    update_data = score_update.model_dump(exclude_unset=True)

    # Validate score type if updating
    if "score_type" in update_data:
        valid_score_types = ["100_point", "20_point", "5_star"]
        if update_data["score_type"] not in valid_score_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid score_type. Must be one of: {valid_score_types}",
            )

    # Update the score entry
    score = wine.scores[score_index]
    for field, value in update_data.items():
        setattr(score, field, value)

    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()

    return WineScoreResponse(
        id=score.id,
        wine_id=wine_id,
        source=score.source,
        score=score.score,
        score_type=score.score_type,
        review_date=score.review_date,
        reviewer=score.reviewer,
        notes=score.notes,
        created_at=score.created_at,
        normalized_score=score.normalized_score,
    )


async def delete_wine_score(
    wine_id: str,
    score_id: str,
    current_user: RequireAuth,
) -> None:
    """Delete a score from a wine."""
    try:
        wine = await Wine.find_one(
            Wine.id == PydanticObjectId(wine_id),
            Wine.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Find and remove score
    original_count = len(wine.scores)
    wine.scores = [s for s in wine.scores if s.id != score_id]

    if len(wine.scores) == original_count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Score with ID {score_id} not found for wine {wine_id}",
        )

    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()
