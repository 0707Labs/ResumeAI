"""/api/admin/billing: the admin billing dashboard. Admins only (users.role = 'admin')."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.billing import billing_config
from app.auth.csrf import require_csrf
from app.auth.deps import current_user
from app.auth.ratelimit import rate_limit
from app.billing.admin import overview, resolve_review
from app.billing.config import BillingConfig
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/billing")


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    return user


@router.get("/overview")
async def billing_overview(days: int = Query(30, ge=1, le=365), _: User = Depends(require_admin),
                           db: AsyncSession = Depends(get_db),
                           config: BillingConfig = Depends(billing_config)) -> dict[str, Any]:
    return await overview(db, config, days)


@router.post("/reviews/{review_id}/resolve", status_code=204,
             dependencies=[Depends(rate_limit("admin_resolve", 60, 60)), Depends(require_csrf)])
async def resolve(review_id: uuid.UUID, _: User = Depends(require_admin),
                  db: AsyncSession = Depends(get_db)) -> None:
    if not await resolve_review(db, review_id):
        raise HTTPException(status_code=404, detail="not_found")
