from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.account import router as account_router
from app.api.analyses import router as analyses_router
from app.api.admin import billing_router as admin_billing_router
from app.api.admin import router as admin_router
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


def create_app() -> FastAPI:
    get_mailer()  # fail at startup, not at the first sign-in, if RT_MAILER is misconfigured
    app = FastAPI(title="Resume Tailor", version="0.1.0")
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
    app.include_router(referrals_router)
    app.include_router(profile_router)
    app.include_router(downloads_router)
    app.include_router(invites_router)
    app.include_router(support_router)
    app.include_router(admin_referrals_router)
    return app


app = create_app()
