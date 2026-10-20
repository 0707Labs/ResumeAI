"""FastAPI dependencies that say who is calling."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import SignedIn, resolve_session
from app.db.models import User
from app.db.session import get_db


async def optional_user(request: Request, db: AsyncSession = Depends(get_db)) -> SignedIn | None:
    return await resolve_session(db, request)


async def current_user(signed_in: SignedIn | None = Depends(optional_user)) -> User:
    """401 without a live session; 403 for a suspended account."""
    if signed_in is None:
        raise HTTPException(status_code=401, detail="not_signed_in")
    if signed_in.user.status != "active":
        raise HTTPException(status_code=403, detail="account_suspended")
    return signed_in.user
