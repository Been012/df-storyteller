"""Image upload, serving, and deletion routes."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from df_storyteller.web.state import (
    get_config as _get_config,
    load_game_state_safe as _load_game_state_safe,
    get_fortress_dir as _get_fortress_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
# Strict pattern: UUID hex + dot + allowed extension only
_SAFE_FILENAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)$")


def _images_dir(fortress_dir: Path) -> Path:
    d = fortress_dir / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path(fortress_dir: Path) -> Path:
    return fortress_dir / "images.json"


def _load_manifest(fortress_dir: Path) -> list[dict]:
    path = _manifest_path(fortress_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_manifest(fortress_dir: Path, manifest: list[dict]) -> None:
    path = _manifest_path(fortress_dir)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


@router.post("/api/images/upload")
async def api_upload_images(files: list[UploadFile] = File(...)):
    """Upload one or more image files. Returns list of {id, url}."""
    config = _get_config()
    _, _, _, metadata = _load_game_state_safe(config)
    fortress_dir = _get_fortress_dir(config, metadata)
    img_dir = _images_dir(fortress_dir)
    manifest = _load_manifest(fortress_dir)

    uploaded = []
    for f in files:
        # Validate extension
        ext = (f.filename or "").rsplit(".", 1)[-1].lower() if f.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            return JSONResponse(
                {"error": f"File type '.{ext}' not allowed. Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}"},
                status_code=400,
            )

        # Read and validate size
        data = await f.read()
        if len(data) > MAX_FILE_SIZE:
            return JSONResponse(
                {"error": f"File '{f.filename}' exceeds 10 MB limit"},
                status_code=400,
            )

        # Generate safe filename
        file_id = uuid.uuid4().hex
        filename = f"{file_id}.{ext}"
        dest = img_dir / filename

        # Write file
        dest.write_bytes(data)

        manifest.append({
            "id": filename,
            "original_name": f.filename or "unknown",
            "ext": ext,
            "size_bytes": len(data),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        })

        uploaded.append({"id": filename, "url": f"/api/images/{filename}"})

    _save_manifest(fortress_dir, manifest)
    return {"images": uploaded}


@router.get("/api/images/{filename}")
async def api_serve_image(filename: str):
    """Serve an uploaded image by filename."""
    # Strict validation to prevent path traversal
    if not _SAFE_FILENAME.match(filename):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    file_path = _images_dir(fortress_dir) / filename

    if not file_path.exists():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    ext = filename.rsplit(".", 1)[-1]
    media_types = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    return FileResponse(file_path, media_type=media_types.get(ext, "application/octet-stream"))


@router.delete("/api/images/{image_id}")
async def api_delete_image(image_id: str):
    """Delete an uploaded image."""
    if not _SAFE_FILENAME.match(image_id):
        return JSONResponse({"error": "Invalid image ID"}, status_code=400)

    config = _get_config()
    fortress_dir = _get_fortress_dir(config)
    file_path = _images_dir(fortress_dir) / image_id

    if file_path.exists():
        file_path.unlink()

    # Remove from manifest
    manifest = _load_manifest(fortress_dir)
    manifest = [m for m in manifest if m.get("id") != image_id]
    _save_manifest(fortress_dir, manifest)

    return {"ok": True}
