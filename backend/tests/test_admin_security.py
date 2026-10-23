"""Admin security: capabilities on every admin route, the role matrix, step-up, the audit
log, the bootstrap CLI, and row-level security for signed-in requests (migration 0010)."""

import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.admin import audit
from app.auth.cli import BootstrapError, bootstrap_admin
from app.auth.roles import CAPABILITIES, STEP_UP, can
from app.main import create_app
from tests.conftest import TABLES
from tests.test_auth_signin import csrf, scalar


@pytest.fixture(autouse=True)
def _clean(request):
    """Tests here also write through pg_engine directly; api_app's truncate only runs when used."""
    yield
    if "pg_engine" in request.fixturenames:
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


def make_user(pg_engine, email: str, role: str = "user") -> uuid.UUID:
    with pg_engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO users (email, email_verified_at, activated_at, age_confirmed_at, terms_version,"
            " terms_accepted_at, role) VALUES (:e, now(), now(), now(), 'v1', now(), :r) RETURNING id"
        ), {"e": email, "r": role}).scalar_one()


def signed_in(new_browser, pg_engine, role: str, email: str | None = None):
    uid = make_user(pg_engine, email or f"{role}-{uuid.uuid4().hex[:6]}@example.com", role)
    browser = new_browser()
    assert browser.post(f"/test/login/{uid}").status_code == 200
    browser.headers.update(csrf(browser))
    return browser, uid


def audit_rows(pg_engine, target_id) -> list[dict]:
    with pg_engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(
            "SELECT * FROM admin_audit_log WHERE target_id = :t ORDER BY id"), {"t": str(target_id)})]


# --- every admin route is guarded --------------------------------------------------------------


def all_routes(routes):
    """FastAPI 0.150 keeps included routers as lazy wrappers; walk into them."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from all_routes(inner.routes)
        else:
            yield route


def admin_routes():
    for route in all_routes(create_app().routes):
        if isinstance(route, APIRoute) and route.path.startswith("/api/admin"):
            yield route


def route_capability(route: APIRoute) -> str | None:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        cap = getattr(dep.call, "capability", None)
        if cap:
            return cap
        stack.extend(dep.dependencies)
    return None


def test_every_admin_route_declares_a_capability():
    routes = list(admin_routes())
    schema_paths = [p for p in create_app().openapi()["paths"] if p.startswith("/api/admin")]
    assert len({r.path for r in routes}) == len(schema_paths) >= 10  # the walk misses nothing
    missing = [f"{sorted(r.methods)} {r.path}" for r in routes if route_capability(r) is None]
    assert missing == []


def test_every_admin_mutation_checks_csrf():
    from app.auth.csrf import require_csrf
    for route in admin_routes():
        if route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            calls = {d.call for d in route.dependant.dependencies}
            assert require_csrf in calls, route.path


def test_capability_matrix():
    assert CAPABILITIES["user"] == frozenset()
    assert CAPABILITIES["support"] < CAPABILITIES["admin"] < CAPABILITIES["superadmin"]
    for cap in ("credits.adjust", "roles.write", "integrations.read", "billing.read", "settings.write"):
        assert not can("support", cap)
    for cap in ("roles.write", "settings.write", "users.delete", "secrets.hint"):
        assert not can("admin", cap) and can("superadmin", cap) and cap in STEP_UP


def fill(path: str) -> str:
    return path.replace("{key}", "invite_only").replace("{referral_id}", str(uuid.uuid4())) \
        .replace("{review_id}", str(uuid.uuid4())).replace("{user_id}", str(uuid.uuid4()))


def test_normal_user_gets_403_from_every_admin_route(new_browser, pg_engine):
    browser, _ = signed_in(new_browser, pg_engine, "user")
    routes = list(admin_routes())
    assert len(routes) >= 10
    for route in routes:
        for method in route.methods:
            res = browser.request(method, fill(route.path), json={"reason": "probe", "value": True, "role": "admin"})
            assert res.status_code == 403, (method, route.path, res.status_code)


def test_signed_out_gets_401_from_admin_reads(client):
    for path in ("/api/admin/settings", "/api/admin/audit", "/api/admin/staff", "/api/admin/billing/overview",
                 "/api/admin/referrals"):
        assert client.get(path).status_code == 401


def test_suspended_staff_are_refused(new_browser, pg_engine):
    browser, uid = signed_in(new_browser, pg_engine, "superadmin")
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'suspended' WHERE id = :u"), {"u": uid})
    assert browser.get("/api/admin/audit").status_code == 403


def test_support_cannot_touch_billing_roles_settings_or_referrals(new_browser, pg_engine):
    support, _ = signed_in(new_browser, pg_engine, "support")
    target = make_user(pg_engine, "target@example.com")
    assert support.get("/api/admin/billing/overview").status_code == 403
    assert support.get("/api/admin/referrals").status_code == 403
    assert support.get("/api/admin/settings").status_code == 403
    assert support.put(f"/api/admin/users/{target}/role", json={"role": "admin", "reason": "please"}).status_code == 403
    assert support.put("/api/admin/settings/invite_only", json={"value": False, "reason": "try"}).status_code == 403
    assert support.get("/api/me").json()["capabilities"] == sorted(CAPABILITIES["support"])


def test_admin_reads_but_cannot_change_settings_or_roles(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin")
    target = make_user(pg_engine, "target@example.com")
    assert admin.get("/api/admin/settings").status_code == 200
    assert admin.get("/api/admin/audit").status_code == 200
    assert admin.get("/api/admin/billing/overview").status_code == 200
    assert admin.put("/api/admin/settings/invite_only", json={"value": False, "reason": "try"}).status_code == 403
    assert admin.put(f"/api/admin/users/{target}/role", json={"role": "admin", "reason": "self"}).status_code == 403


def test_role_comes_from_the_database_not_the_client(new_browser, pg_engine):
    browser, uid = signed_in(new_browser, pg_engine, "superadmin")
    assert browser.get("/api/admin/audit").status_code == 200
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'user' WHERE id = :u"), {"u": uid})
    assert browser.get("/api/admin/audit", headers={"X-Role": "superadmin"}).status_code == 403


# --- step-up -----------------------------------------------------------------------------------


def test_superadmin_actions_need_a_recent_sign_in(new_browser, pg_engine):
    browser, uid = signed_in(new_browser, pg_engine, "superadmin")
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE auth_sessions SET reauth_at = now() - interval '11 minutes'"
                          " WHERE user_id = :u"), {"u": uid})
    body = {"value": False, "reason": "launch prep"}
    res = browser.put("/api/admin/settings/invite_only", json=body)
    assert (res.status_code, res.json()["detail"]) == (401, "reauth_required")
    assert browser.get("/api/admin/audit").status_code == 200  # reads need no step-up

    assert browser.post(f"/test/login/{uid}").status_code == 200  # signing in again
    browser.headers.update(csrf(browser))
    assert browser.put("/api/admin/settings/invite_only", json=body).status_code == 200


# --- settings and roles are audited ------------------------------------------------------------


def test_setting_change_is_validated_and_audited(new_browser, pg_engine):
    browser, uid = signed_in(new_browser, pg_engine, "superadmin")
    assert browser.put("/api/admin/settings/no_such_key", json={"value": 1, "reason": "probe"}).status_code == 404
    assert browser.put("/api/admin/settings/invite_only", json={"value": "maybe", "reason": "x" * 3}).status_code == 422
    res = browser.put("/api/admin/settings/analyses_paused", json={"value": True, "reason": "budget hit"})
    assert res.status_code == 200
    assert res.json()["values"]["analyses_paused"] is True and res.json()["overridden"] == ["analyses_paused"]
    [row] = audit_rows(pg_engine, "analyses_paused")[-1:]
    assert (row["actor_id"], row["actor_role"], row["action"], row["reason"]) == (uid, "superadmin", "settings.update",
                                                                                 "budget hit")
    assert (row["before"], row["after"]) == ({"analyses_paused": False}, {"analyses_paused": True})
    assert row["ip_hmac"] and row["ip_hmac"] != "testclient"

    res = browser.post("/api/admin/settings/analyses_paused/reset", json={"reason": "budget reset"})
    assert res.json()["values"]["analyses_paused"] is False and res.json()["overridden"] == []
    assert audit_rows(pg_engine, "analyses_paused")[-1]["action"] == "settings.reset"


def test_role_change_rules_and_audit(new_browser, pg_engine):
    boss, boss_id = signed_in(new_browser, pg_engine, "superadmin")
    target = make_user(pg_engine, "target@example.com")
    res = boss.put(f"/api/admin/users/{boss_id}/role", json={"role": "user", "reason": "step down"})
    assert (res.status_code, res.json()["detail"]) == (409, "own_role")
    assert boss.put(f"/api/admin/users/{target}/role", json={"role": "support", "reason": "joins support"}).status_code == 204
    assert scalar(pg_engine, "SELECT role FROM users WHERE id = :u", u=target) == "support"
    [row] = audit_rows(pg_engine, target)
    assert (row["action"], row["before"], row["after"]) == ("roles.change", {"role": "user"}, {"role": "support"})
    assert boss.put(f"/api/admin/users/{target}/role", json={"role": "god", "reason": "x" * 5}).status_code == 422
    assert boss.put(f"/api/admin/users/{uuid.uuid4()}/role",
                    json={"role": "admin", "reason": "ghost"}).status_code == 404


def test_last_superadmin_cannot_be_demoted(new_browser, pg_engine):
    a, a_id = signed_in(new_browser, pg_engine, "superadmin")
    b, b_id = signed_in(new_browser, pg_engine, "superadmin")
    assert a.put(f"/api/admin/users/{b_id}/role", json={"role": "admin", "reason": "rotation"}).status_code == 204
    # b is admin now; nobody else can demote a, and a can't demote itself.
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET role = 'superadmin' WHERE id = :u"), {"u": b_id})
    assert b.put(f"/api/admin/users/{a_id}/role", json={"role": "user", "reason": "rotation"}).status_code == 204
    res = a.put(f"/api/admin/users/{b_id}/role", json={"role": "user", "reason": "rotation"})
    assert res.status_code == 403  # a is a user now
    assert scalar(pg_engine, "SELECT count(*) FROM users WHERE role = 'superadmin'") == 1


def test_referral_decisions_and_review_resolution_are_audited(new_browser, pg_engine):
    admin, admin_id = signed_in(new_browser, pg_engine, "admin")
    referrer, referee = make_user(pg_engine, "r@example.com"), make_user(pg_engine, "f@example.com")
    with pg_engine.begin() as conn:
        rid = conn.execute(text("INSERT INTO referrals (referrer_id, referee_id, needs_review) VALUES (:a, :b, true)"
                                " RETURNING id"), {"a": referrer, "b": referee}).scalar_one()
        review = conn.execute(text("INSERT INTO billing_reviews (kind, dedupe_key) VALUES ('partial_refund', :k)"
                                   " RETURNING id"), {"k": uuid.uuid4().hex}).scalar_one()
    assert admin.post(f"/api/admin/referrals/{rid}/reject", json={"reason": "same household"}).status_code == 204
    [row] = audit_rows(pg_engine, rid)
    assert (row["action"], row["actor_id"], row["reason"]) == ("referrals.reject", admin_id, "same household")
    assert (row["before"]["status"], row["after"]["status"]) == ("pending", "rejected")

    assert admin.post(f"/api/admin/billing/reviews/{review}/resolve").status_code == 204
    assert [r["action"] for r in audit_rows(pg_engine, review)] == ["billing.resolve_review"]
    assert admin.post(f"/api/admin/billing/reviews/{review}/resolve").status_code == 404
    assert len(audit_rows(pg_engine, review)) == 1  # no entry for a change that didn't happen


# --- the audit log itself ----------------------------------------------------------------------


def test_audit_log_is_append_only(pg_engine):
    with pg_engine.begin() as conn:
        rid = conn.execute(text("INSERT INTO admin_audit_log (actor_role, action) VALUES ('system', 'test.append')"
                                " RETURNING id")).scalar_one()
    for sql in ("UPDATE admin_audit_log SET reason = 'x' WHERE id = :i", "DELETE FROM admin_audit_log WHERE id = :i",
                "TRUNCATE admin_audit_log"):
        with pytest.raises(DBAPIError, match="append-only"), pg_engine.begin() as conn:
            conn.execute(text(sql), {"i": rid})


def test_audit_summaries_refuse_content_and_bulk():
    db = Session()
    with pytest.raises(audit.AuditError):
        audit.record(db, None, "users.view", after={"resume": {"summary": "..."}})
    with pytest.raises(audit.AuditError):
        audit.record(db, None, "users.view", before={"nested": [{"JD": "text"}]})
    with pytest.raises(audit.AuditError):
        audit.record(db, None, "users.view", after={"ids": list(range(1000))})
    row = audit.record(db, None, "credits.adjust", target_id=uuid.UUID(int=1), after={"delta": 5, "at": uuid.UUID(int=2)})
    assert row.after == {"delta": 5, "at": str(uuid.UUID(int=2))} and row.actor_role == "system"


def test_audit_viewer_pages_and_filters(new_browser, pg_engine):
    admin, _ = signed_in(new_browser, pg_engine, "admin")
    target = uuid.uuid4()
    with pg_engine.begin() as conn:
        for i in range(5):
            conn.execute(text("INSERT INTO admin_audit_log (actor_role, action, target_type, target_id)"
                              " VALUES ('system', 'test.page', 'thing', :t)"), {"t": str(target)})
    first = admin.get("/api/admin/audit", params={"target_id": str(target), "limit": 3}).json()
    assert len(first["entries"]) == 3 and first["next_before_id"] is not None
    rest = admin.get("/api/admin/audit", params={"target_id": str(target), "limit": 3,
                                                  "before_id": first["next_before_id"]}).json()
    assert len(rest["entries"]) == 2 and rest["next_before_id"] is None
    ids = [e["id"] for e in first["entries"] + rest["entries"]]
    assert ids == sorted(ids, reverse=True)


# --- bootstrap ---------------------------------------------------------------------------------


def test_bootstrap_admin(pg_engine):
    first = make_user(pg_engine, "founder@example.com")
    with Session(pg_engine) as db:
        with pytest.raises(BootstrapError, match="sign up first"):
            bootstrap_admin(db, "nobody@example.com")
        with pytest.raises(BootstrapError, match="not set"):
            bootstrap_admin(db, "  ")
        assert bootstrap_admin(db, " Founder@Example.com ") == "promoted to superadmin"
        assert bootstrap_admin(db, "founder@example.com") == "already superadmin"
        second = make_user(pg_engine, "cofounder@example.com")
        with pytest.raises(BootstrapError, match="already exists"):
            bootstrap_admin(db, "cofounder@example.com")
        assert bootstrap_admin(db, "cofounder@example.com", force=True) == "promoted to superadmin"
    [row] = audit_rows(pg_engine, first)
    assert (row["actor_id"], row["actor_role"], row["action"]) == (None, "system", "roles.bootstrap")
    assert audit_rows(pg_engine, second)[0]["after"]["forced"] is True


# --- row-level security ------------------------------------------------------------------------


def as_app_user(conn, user_id):
    conn.execute(text("SET LOCAL ROLE rt_app"))
    conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


@pytest.mark.parametrize("table", ["admin_audit_log", "app_settings", "llm_usage", "invites", "invite_redemptions",
                                   "waitlist", "pending_auth", "email_tokens", "processed_webhook_events",
                                   "billing_reviews"])
def test_rt_app_cannot_read_staff_or_flow_tables(pg_engine, user_id, table):
    with pytest.raises(ProgrammingError, match="permission denied"), pg_engine.connect() as conn, conn.begin():
        as_app_user(conn, user_id)
        conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


def test_rt_app_sees_only_its_own_rows(pg_engine):
    a, b = make_user(pg_engine, "a@example.com"), make_user(pg_engine, "b@example.com")
    with pg_engine.begin() as conn:
        for uid in (a, b):
            conn.execute(text("INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until)"
                              " VALUES (:u, :k, '{}', '{}', 'x', now())"), {"u": uid, "k": uuid.uuid4().hex})
    with pg_engine.connect() as conn, conn.begin():
        as_app_user(conn, a)
        assert conn.execute(text("SELECT id FROM users")).scalars().all() == [a]
        assert conn.execute(text("SELECT count(*) FROM analyses")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM analyses WHERE user_id = :b"), {"b": b}).scalar_one() == 0
        # Writes to someone else's row match nothing; inserting one for them is refused.
        assert conn.execute(text("UPDATE users SET name = 'x' WHERE id = :b"), {"b": b}).rowcount == 0
    with pytest.raises(ProgrammingError, match="row-level security"), pg_engine.connect() as conn, conn.begin():
        as_app_user(conn, a)
        conn.execute(text("INSERT INTO analyses (user_id, idempotency_key, resume, jd, inputs_sha256, usable_until)"
                          " VALUES (:b, 'k', '{}', '{}', 'x', now())"), {"b": b})


def test_rt_app_cannot_change_its_own_role_or_status(pg_engine, user_id):
    for column in ("role = 'superadmin'", "status = 'active'", "email = 'x@example.com'"):
        with pytest.raises(ProgrammingError, match="permission denied"), pg_engine.connect() as conn, conn.begin():
            as_app_user(conn, user_id)
            conn.execute(text(f"UPDATE users SET {column} WHERE id = :u"), {"u": user_id})


def test_without_a_user_id_rt_app_sees_nothing(pg_engine, user_id):
    with pg_engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE rt_app"))
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_signed_in_requests_run_as_rt_app(new_browser, pg_engine, api_app):
    """The request's DB session switches role once the user is known, and keeps it
    across commits; service_scope steps out and back."""
    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.auth.deps import current_user
    from app.db.rls import service_scope
    from app.db.session import get_db

    @api_app.get("/test/whoami")
    async def whoami(_=Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
        first = (await db.execute(text("SELECT current_user, count(*) FROM users"))).one()
        await db.commit()
        after_commit = (await db.execute(text("SELECT current_user"))).scalar_one()
        async with service_scope(db):
            service = (await db.execute(text("SELECT current_user, count(*) FROM users"))).one()
        back = (await db.execute(text("SELECT current_user"))).scalar_one()
        return {"first": list(first), "after_commit": after_commit, "service": list(service), "back": back}

    make_user(pg_engine, "someone-else@example.com")
    browser, _ = signed_in(new_browser, pg_engine, "user")
    out = browser.get("/test/whoami").json()
    assert out["first"] == ["rt_app", 1]
    assert out["after_commit"] == "rt_app" and out["back"] == "rt_app"
    assert out["service"][0] != "rt_app" and out["service"][1] >= 2
