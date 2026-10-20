from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.account import router as account_router
from app.api.auth import router as auth_router
from app.api.oauth import router as oauth_router
from app.api.routes import router
from app.api.signin import router as signin_router
from app.config import get_settings


def create_app() -> FastAPI:
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
    return app


app = create_app()
