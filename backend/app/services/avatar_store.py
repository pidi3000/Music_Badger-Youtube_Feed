"""Downloads a channel's YouTube avatar once and caches it on local disk, so
the UI never hotlinks YouTube's image CDN directly and avatars keep working
even if YouTube later changes/removes the source image. Best-effort: a
failed download (network error, bad status, unrecognized content type)
leaves the caller to fall back to the remote URL (or None) rather than
blocking channel creation/import on it.
"""

import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
_KNOWN_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}


def _avatar_dir() -> Path:
    path = Path(get_config().media_dir) / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _guess_extension(content_type: str | None, url: str) -> str:
    if content_type:
        ext = _EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())
        if ext:
            return ext
    suffix = Path(urlparse(url).path).suffix.lstrip(".").lower()
    return suffix if suffix in _KNOWN_EXTENSIONS else "jpg"


async def store_channel_avatar(
    http_client: httpx.AsyncClient, youtube_channel_id: str, remote_url: str | None
) -> str | None:
    """Downloads `remote_url` and returns a local `/media/...` URL to store
    on Channel.thumbnail_url, or None if there was nothing to fetch or the
    download failed."""

    if not remote_url:
        return None

    try:
        response = await http_client.get(remote_url, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("avatar download failed for channel %s: %s", youtube_channel_id, exc)
        return None

    if not response.content:
        return None

    ext = _guess_extension(response.headers.get("content-type"), remote_url)
    filename = f"{youtube_channel_id}.{ext}"
    (_avatar_dir() / filename).write_bytes(response.content)
    return f"/media/avatars/{filename}"
