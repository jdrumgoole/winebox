"""Authenticated wine-label image serving.

Replaces the previous `app.mount("/api/images", StaticFiles(...))` mount,
which served any image to any unauthenticated requester that knew (or
guessed/leaked) the UUID filename. Now every fetch requires a valid JWT
and the image must belong to a wine owned by the requesting user.
"""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from winebox.models import Wine
from winebox.services.auth import RequireAuth
from winebox.services.image_storage import ImageStorageService

router = APIRouter()

_image_storage = ImageStorageService()

# Per-extension fallback content types for files mimetypes doesn't recognise.
_EXT_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def _content_type_for(file_path: Path) -> str:
    ctype, _ = mimetypes.guess_type(file_path.name)
    if ctype:
        return ctype
    return _EXT_CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")


@router.get("/{filename:path}")
async def get_label_image(
    filename: str,
    current_user: RequireAuth,
) -> FileResponse:
    """Serve a wine label image to its owner only.

    Behaviour:
    - Path-traversal attempts (`..`, slashes, absolute paths) → 404 via
      `_safe_resolve` so we never leak whether a sibling file exists.
    - Filename not referenced by any of the requester's wines → 404. This
      uniformly hides both 'image does not exist' and 'image belongs to
      another user' so the endpoint cannot be used to enumerate filenames
      across users.
    - Owned and on disk → returned as `image/*` with `Cache-Control: private`
      so shared proxies and CDNs do not cache cross-user.
    """
    # Defence in depth — also rejects the `{filename:path}` route variant
    # being abused with a slash.
    file_path = _image_storage._safe_resolve(filename)
    if file_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Ownership check first — never touch the filesystem before we've proven
    # the requester owns a wine that references this filename.
    owned = await Wine.find_one({
        "owner_id": current_user.id,
        "$or": [
            {"front_label_image_path": filename},
            {"back_label_image_path": filename},
        ],
    })
    if owned is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return FileResponse(
        file_path,
        media_type=_content_type_for(file_path),
        headers={"Cache-Control": "private, max-age=3600"},
    )
