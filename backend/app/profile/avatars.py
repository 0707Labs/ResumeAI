"""Profile pictures: we store our own re-encoded copy, never a link to someone else's.

Every picture, uploaded or from Google/GitHub, goes through `normalize()`: decoded with
Pillow under a pixel cap (no decompression bombs), centre-cropped square, resized to
256 px and re-encoded as WebP. Re-encoding drops EXIF and anything else riding along
in the file (location, camera, embedded payloads).

Provider pictures come from the verified identity (Google's `picture` claim, GitHub's
`avatar_url`) and are fetched server-side once, only from the providers' image hosts,
over https, without following redirects, under a size cap and a short timeout. Failing
to get one never fails a sign-in. A user who removed their picture doesn't get the
provider's back on the next sign-in.
"""

import hashlib
import io
import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx2
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import oauth
from app.db.models import User, UserAvatar

log = logging.getLogger("app.profile")

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000
SIZE = 256
MAX_OUTPUT_BYTES = 262_144
ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
PROVIDER_HOSTS = ("googleusercontent.com", "githubusercontent.com")
FETCH_TIMEOUT = 3.0


class BadImage(ValueError):
    """Not a picture we accept; the message is safe to show."""


def normalize(raw: bytes) -> bytes:
    if not raw:
        raise BadImage("empty")
    if len(raw) > MAX_INPUT_BYTES:
        raise BadImage("too_large")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in ACCEPTED_FORMATS:
                raise BadImage("unsupported_type")
            width, height = probe.size
            if width * height > MAX_PIXELS or min(width, height) < 1:
                raise BadImage("too_large")
            probe.seek(0)
            image = probe.convert("RGBA" if probe.mode in ("RGBA", "LA", "P") else "RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, EOFError):
        raise BadImage("unsupported_type") from None
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="WEBP", quality=85, method=4)
    data = out.getvalue()
    if len(data) > MAX_OUTPUT_BYTES:  # can't really happen at 256 px, but the column refuses it anyway
        raise BadImage("too_large")
    return data


def provider_picture_ok(url: str | None) -> bool:
    if not url or len(url) > 1000:
        return False
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and parts.port in (None, 443) and not parts.username
            and any(host == h or host.endswith("." + h) for h in PROVIDER_HOSTS))


async def save(db: AsyncSession, user_id: uuid.UUID, data: bytes, source: str) -> str:
    """Store an already-normalized picture. Caller commits. Returns its sha256."""
    sha = hashlib.sha256(data).hexdigest()
    values = {"content_type": "image/webp", "data": data, "sha256": sha, "source": source}
    await db.execute(insert(UserAvatar).values(user_id=user_id, **values).on_conflict_do_update(
        index_elements=[UserAvatar.user_id], set_={**values, "updated_at": datetime.now(UTC)}))
    return sha


async def remove(db: AsyncSession, user: User) -> None:
    """Back to initials, and remember it so sign-in doesn't restore the provider's. Caller commits."""
    await db.execute(delete(UserAvatar).where(UserAvatar.user_id == user.id))
    user.avatar_removed_at = datetime.now(UTC)


def url(sha: str | None) -> str | None:
    """Same-origin, versioned so a new picture isn't served from cache."""
    return f"/api/profile/avatar?v={sha[:16]}" if sha else None


async def current_sha(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    return await db.scalar(select(UserAvatar.sha256).where(UserAvatar.user_id == user_id))


async def _fetch(url: str) -> bytes | None:
    async with httpx2.AsyncClient(timeout=FETCH_TIMEOUT, transport=oauth._transport,  # noqa: SLF001 - tests mock it
                                  follow_redirects=False) as http:
        async with http.stream("GET", url, headers={"Accept": "image/*"}) as res:
            if res.status_code != 200:
                return None
            body = bytearray()
            async for chunk in res.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_INPUT_BYTES:
                    return None
            return bytes(body)


async def import_provider_picture(db: AsyncSession, user: User, url: str | None) -> bool:
    """Best effort: give a user without a picture their Google/GitHub one. Commits on success.
    Never raises; a sign-in must not fail over a picture."""
    try:
        if not provider_picture_ok(url) or user.avatar_removed_at is not None:
            return False
        if await current_sha(db, user.id) is not None:
            return False
        raw = await _fetch(url)  # type: ignore[arg-type]
        if raw is None:
            return False
        await save(db, user.id, normalize(raw), "provider")
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - see docstring
        await db.rollback()
        log.info("provider picture not imported: %s", exc.__class__.__name__)
        return False
