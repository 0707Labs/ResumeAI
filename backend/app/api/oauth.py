"""Continue with Google / GitHub.

GET /api/auth/{provider}/start     -> 302 to the provider (state + PKCE + nonce in a signed cookie)
GET /api/auth/{provider}/callback  -> 302 to where the user goes next:
    signed in                    -> the `next` page (allowlisted), default /
    new, verified email          -> /signup/invite   (no user row; pending identity)
    new, no verified email       -> /signup/verify-email
    failure                      -> /login?error=<code>

Both are top-level browser navigations (GETs), so CSRF is covered by `state`."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.signin import sign_in_or_gate
from app.auth import oauth
from app.auth.events import log_auth_event
from app.auth.ratelimit import rate_limit
from app.db.session import get_db

router = APIRouter(prefix="/api/auth")

NEXT_STEP = {"invite": "/signup/invite", "verify_email": "/signup/verify-email"}


def _to_login(provider: str, code: str) -> RedirectResponse:
    log_auth_event("oauth_failed", outcome="denied", provider=provider, reason=code)  # type: ignore[arg-type]
    return RedirectResponse(f"/login?error={code}", status_code=302)


@router.get("/{provider}/start", dependencies=[Depends(rate_limit("oauth_start", 20, 60))])
async def start(provider: Literal["google", "github"], next: str | None = None) -> RedirectResponse:
    if oauth.credentials(provider) is None:
        return _to_login(provider, "provider_unavailable")
    response = RedirectResponse("", status_code=302)
    response.headers["location"] = oauth.begin(provider, next, response)
    log_auth_event("oauth_started", provider=provider)
    return response


@router.get("/{provider}/callback", dependencies=[Depends(rate_limit("oauth_callback", 30, 60))])
async def callback(
    provider: Literal["google", "github"],
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    response = RedirectResponse("/", status_code=302)
    flow = oauth.take_flow(request, response)  # single use: cleared on every outcome

    def fail(reason: str) -> RedirectResponse:
        failed = _to_login(provider, reason)
        failed.raw_headers.extend(h for h in response.raw_headers if h[0] == b"set-cookie")
        return failed

    if flow is None or not oauth.state_matches(flow, provider, state):
        return fail("oauth_state")
    if error:
        return fail("cancelled" if error == "access_denied" else "provider_unavailable")
    if not code or oauth.credentials(provider) is None:
        return fail("provider_unavailable")
    try:
        identity = await oauth.fetch_identity(flow, code)
    except oauth.ProviderError as exc:
        return fail(exc.code)

    try:
        step = await sign_in_or_gate(
            db, request, response, provider=identity.provider,
            provider_account_id=identity.provider_account_id, verified_email=identity.verified_email,
        )
    except HTTPException as exc:
        return fail(str(exc.detail))
    response.headers["location"] = flow.next if step.next == "signed_in" else NEXT_STEP[step.next]
    return response
