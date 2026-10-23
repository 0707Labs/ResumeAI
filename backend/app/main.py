import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import counters
from app.api.account import router as account_router
from app.api.analyses import router as analyses_router
from app.api.admin import billing_router as admin_billing_router
from app.api.admin import router as admin_router
from app.api.admin_invites import router as admin_invites_router
from app.api.admin_money import router as admin_money_router
from app.api.admin_ops import public_router as metrics_router
from app.api.admin_ops import router as admin_ops_router
from app.api.admin_support import router as admin_support_router
from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.downloads import router as downloads_router
from app.api.invites import router as invites_router
from app.api.oauth import router as oauth_router
from app.api.profile import router as profile_router
from app.api.referrals import admin_router as admin_referrals_router
from app.api.referrals import router as referrals_router
from app.api.routes import router
from app.api.signin import router as signin_router
from app.api.support import router as support_router
from app.auth.mailer import get_mailer
from app.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(counters.flusher())  # dashboard counts, flushed every minute
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    get_mailer()  # fail at startup, not at the first sign-in, if RT_MAILER is misconfigured
    app = FastAPI(title="Resume Tailor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],  # so the browser sees export filenames
    )

    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(signin_router)
    app.include_router(oauth_router)
    app.include_router(account_router)
    app.include_router(billing_router)
    app.include_router(analyses_router)
    app.include_router(admin_router)
    app.include_router(admin_billing_router)
    app.include_router(admin_users_router)
    app.include_router(admin_invites_router)
    app.include_router(admin_support_router)
    app.include_router(admin_money_router)
    app.include_router(admin_ops_router)
    app.include_router(metrics_router)
    app.include_router(referrals_router)
    app.include_router(profile_router)
    app.include_router(downloads_router)
    app.include_router(invites_router)
    app.include_router(support_router)
    app.include_router(admin_referrals_router)
    return app


app = create_app()
