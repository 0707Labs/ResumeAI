"""Continue with Google / GitHub, and "Connect" from /account.

GET /api/auth/{provider}/start[?intent=link]  -> 302 to the provider (state + PKCE + nonce in a signed cookie)
GET /api/auth/{provider}/callback             -> 302 to where the user goes next:
    signed in                    -> the `next` page (allowlisted), default /app
    new, verified email          -> /signup/invite, or /signup/consent when signup is open (no user row yet)
    new, no verified email       -> /signup/verify-email
    linked (intent=link)         -> /account?linked=<provider>
    failure                      -> /signin?error=<code>  (link flows: /account?error=<code>)

Both are top-level browser navigations (GETs), so CSRF is covered by `state`."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.signin import sign_in_or_gate
from app.auth import oauth
from app.auth.account import AccountError, link
from app.auth.deps import optional_user
from app.auth.events import log_auth_event
from app.auth.ratelimit import rate_limit
from app.auth.sessions import SignedIn, resolve_session, start_session
from app.db.session import get_db

router = APIRouter(prefix="/api/auth")

NEXT_STEP = {"invite": "/signup/invite", "consent": "/signup/consent", "verify_email": "/signup/verify-email"}


def _failed(provider: str, code: str, intent: str = "login") -> RedirectResponse:
    log_auth_event("oauth_failed", outcome="denied", provider=provider, reason=code)  # type: ignore[arg-type]
    page = "/account" if intent == "link" else "/signin"
    return RedirectResponse(f"{page}?error={code}", status_code=302)


@router.get("/{provider}/start", dependencies=[Depends(rate_limit("oauth_start", 20, 60))])
async def start(
    provider: Literal["google", "github"],
    next: str | None = None,
    intent: Literal["login", "link"] = "login",
    signed_in: SignedIn | None = Depends(optional_user),
) -> RedirectResponse:
    if oauth.credentials(provider) is None:
        return _failed(provider, "provider_unavailable", intent)
    user_id = None
    if intent == "link":
        if signed_in is None or signed_in.user.status != "active":
            return _failed(provider, "not_signed_in")
        user_id = str(signed_in.user.id)
    response = RedirectResponse("", status_code=302)
    response.headers["location"] = oauth.begin(provider, next, response, intent=intent, user_id=user_id)
    log_auth_event("oauth_started", provider=provider, reason=intent)
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
    response = RedirectResponse(oauth.DEFAULT_NEXT, status_code=302)
    flow = oauth.take_flow(request, response)  # single use: cleared on every outcome
    intent = flow.intent if flow else "login"

    def fail(reason: str) -> RedirectResponse:
        failed = _failed(provider, reason, intent)
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

    if flow.intent == "link":
        return await _finish_link(db, request, response, flow, identity, fail)
    try:
        step = await sign_in_or_gate(
            db, request, response, provider=identity.provider,
            provider_account_id=identity.provider_account_id, verified_email=identity.verified_email,
        )
    except HTTPException as exc:
        return fail(str(exc.detail))
    response.headers["location"] = flow.next if step.next == "signed_in" else NEXT_STEP[step.next]
    return response


async def _finish_link(db, request, response, flow, identity, fail) -> RedirectResponse:
    """Connect this provider identity to the user who started the flow, if they
    are still the one signed in. The identity must assert a verified email."""
    signed_in = await resolve_session(db, request)
    if signed_in is None or str(signed_in.user.id) != flow.user_id or signed_in.user.status != "active":
        return fail("not_signed_in")
    if identity.verified_email is None:
        return fail("email_unverified")
    user = signed_in.user
    try:
        result = await link(db, user, identity.provider, identity.provider_account_id, identity.verified_email)
    except AccountError as exc:
        log_auth_event("account_link_failed", outcome="denied", user_id=user.id,
                       provider=identity.provider, reason=exc.code)
        return fail(exc.code)
    if result == "linked":
        await start_session(db, request, response, user, provider=identity.provider, event="account_linked")
    response.headers["location"] = f"/account?linked={identity.provider}"
    return response
