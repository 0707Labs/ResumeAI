"""Google and GitHub sign-in: authorization URL, code exchange, verified identity.

Identity only. Scopes are the minimum (Google: openid email profile; GitHub:
read:user user:email), and provider tokens are used once and dropped, never stored.

Every flow carries state (CSRF), PKCE S256 (both providers support it) and,
for Google, an OIDC nonce. They live in one signed, HttpOnly, 10-minute cookie
that the callback consumes."""

import base64
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Literal

import httpx2
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import Request, Response
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from app.auth.cookies import clear_cookie, cookie_name, read_cookie, set_cookie
from app.auth.signing import sign, unsign
from app.config import get_settings

OAuthProvider = Literal["google", "github"]
FLOW_TTL = 600
HTTP_TIMEOUT = 10.0


@dataclass(frozen=True)
class ProviderConfig:
    authorize_url: str
    token_url: str
    scope: str


PROVIDERS: dict[str, ProviderConfig] = {
    "google": ProviderConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email profile",
    ),
    "github": ProviderConfig(
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scope="read:user user:email",
    ),
}
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

# Where a signed-in user may be sent back to. Relative paths only.
NEXT_PREFIXES = ("/app", "/account", "/analysis", "/review", "/score", "/mentor", "/export", "/pricing", "/billing")
DEFAULT_NEXT = "/app"  # the tailoring workspace
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9/_-]*$")


class ProviderError(Exception):
    """The provider failed or refused (code: provider_unavailable | cancelled)."""

    def __init__(self, code: str = "provider_unavailable"):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Identity:
    provider: OAuthProvider
    provider_account_id: str
    verified_email: str | None  # None: the provider asserted no verified email


@dataclass(frozen=True)
class Flow:
    provider: OAuthProvider
    state: str
    verifier: str
    nonce: str
    next: str
    intent: Literal["login", "link"] = "login"
    user_id: str | None = None  # for "link": the signed-in user who started it


def credentials(provider: OAuthProvider) -> tuple[str, str] | None:
    s = get_settings()
    pair = (s.google_client_id, s.google_client_secret) if provider == "google" else (
        s.github_client_id, s.github_client_secret)
    return pair if all(pair) else None


def redirect_uri(provider: OAuthProvider) -> str:
    """Fixed, built only from RT_PUBLIC_URL; register exactly this with the provider."""
    return f"{get_settings().public_url}/api/auth/{provider}/callback"


def safe_next(path: str | None) -> str:
    """A post-sign-in destination on our own site, or the workspace."""
    if not path or not _SAFE_PATH.match(path) or path.startswith("//"):
        return DEFAULT_NEXT
    if path == "/" or any(path == p or path.startswith(p + "/") for p in NEXT_PREFIXES):
        return path
    return DEFAULT_NEXT


_transport: httpx2.AsyncBaseTransport | None = None  # tests inject a mock; None = real network


def set_transport(transport: httpx2.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client(provider: OAuthProvider) -> AsyncOAuth2Client:
    client_id, client_secret = credentials(provider)  # type: ignore[misc]  # callers checked
    return AsyncOAuth2Client(
        client_id=client_id,
        client_secret=client_secret,
        scope=PROVIDERS[provider].scope,
        redirect_uri=redirect_uri(provider),
        token_endpoint_auth_method="client_secret_post",
        code_challenge_method="S256",
        timeout=HTTP_TIMEOUT,
        transport=_transport,
    )


# --- flow cookie -----------------------------------------------------------------------------


def flow_cookie() -> str:
    return cookie_name("rt_oauth")


def begin(provider: OAuthProvider, next_path: str | None, response: Response, *,
          intent: Literal["login", "link"] = "login", user_id: str | None = None) -> str:
    """Store a new flow in the cookie and return the provider's authorization URL."""
    flow = Flow(provider=provider, state=secrets.token_urlsafe(32), verifier=secrets.token_urlsafe(48),
                nonce=secrets.token_urlsafe(24), next=safe_next(next_path), intent=intent, user_id=user_id)
    payload = base64.urlsafe_b64encode(json.dumps(flow.__dict__).encode()).decode().rstrip("=")
    set_cookie(response, flow_cookie(), sign("oauth", payload), max_age=FLOW_TTL)
    extra = {"nonce": flow.nonce} if provider == "google" else {}
    url, _ = _client(provider).create_authorization_url(
        PROVIDERS[provider].authorize_url, state=flow.state, code_verifier=flow.verifier, **extra
    )
    return url


def take_flow(request: Request, response: Response) -> Flow | None:
    """The flow from the cookie (signed, unexpired), cleared so it can't be replayed."""
    clear_cookie(response, flow_cookie())
    payload = unsign("oauth", read_cookie(request, flow_cookie()))
    if payload is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return Flow(**data)
    except (ValueError, TypeError):
        return None


def state_matches(flow: Flow, provider: str, state: str | None) -> bool:
    return flow.provider == provider and state is not None and secrets.compare_digest(flow.state, state)


# --- identity ------------------------------------------------------------------------------------


async def fetch_identity(flow: Flow, code: str) -> Identity:
    """Exchange the code (with the PKCE verifier) and read who this is. Raises ProviderError."""
    try:
        async with _client(flow.provider) as client:
            token = await client.fetch_token(
                PROVIDERS[flow.provider].token_url, code=code, code_verifier=flow.verifier,
                headers={"Accept": "application/json"},
            )
            if "error" in token:
                raise ProviderError()
            if flow.provider == "google":
                return await _google_identity(token, flow.nonce)
            return await _github_identity(client)
    except (AuthlibBaseError, httpx2.HTTPError, JoseError, KeyError, ValueError, TypeError) as exc:
        # Bad/missing fields, failed exchange, bad id_token, network: all the provider's side.
        raise ProviderError() from exc


_jwks: dict[str, object] = {"keys": None, "at": 0.0}


async def _google_keys(refresh: bool = False) -> KeySet:
    if refresh or _jwks["keys"] is None or time.monotonic() - _jwks["at"] > 3600:
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT, transport=_transport) as http:
            res = await http.get(GOOGLE_JWKS_URL)
            res.raise_for_status()
        _jwks.update(keys=KeySet.import_key_set(res.json()), at=time.monotonic())
    return _jwks["keys"]  # type: ignore[return-value]


async def _google_identity(token: dict, nonce: str) -> Identity:
    """Validate the id_token: signature (Google JWKS), iss, aud, exp, nonce."""
    id_token = token["id_token"]
    try:
        decoded = jwt.decode(id_token, await _google_keys(), algorithms=["RS256"])
    except JoseError:
        decoded = jwt.decode(id_token, await _google_keys(refresh=True), algorithms=["RS256"])  # key rotation
    jwt.JWTClaimsRegistry(
        iss={"essential": True, "values": GOOGLE_ISSUERS},
        aud={"essential": True, "value": credentials("google")[0]},  # type: ignore[index]
        exp={"essential": True},
        sub={"essential": True},
        nonce={"essential": True, "value": nonce},
    ).validate(decoded.claims)
    claims = decoded.claims
    email = claims.get("email")
    verified = claims.get("email_verified") is True and isinstance(email, str)
    return Identity("google", str(claims["sub"]), email.strip().lower() if verified else None)


async def _github_identity(client: AsyncOAuth2Client) -> Identity:
    """GitHub ids are numeric and stable. The email is the primary *verified*
    address from /user/emails; the public profile email is never used."""
    user = await client.get(f"{GITHUB_API}/user", headers=GITHUB_HEADERS)
    user.raise_for_status()
    emails = await client.get(f"{GITHUB_API}/user/emails", headers=GITHUB_HEADERS)
    emails.raise_for_status()
    primary = next((e for e in emails.json()
                    if e.get("primary") is True and e.get("verified") is True and isinstance(e.get("email"), str)),
                   None)
    return Identity("github", str(user.json()["id"]), primary["email"].strip().lower() if primary else None)
