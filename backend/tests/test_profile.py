"""Profile (migration 0012): pictures (upload, provider import, removal), phone, saved-resume
versions, tailorings list/detail/delete, consent history and the research toggle, data
export, and user A never seeing user B's data."""

import io
import json

import pytest
from PIL import Image
from sqlalchemy import text

from app.profile import avatars
from tests.conftest import fixture_text
from tests.test_admin_security import make_user
from tests.test_auth_oauth import google, mock, providers, where  # noqa: F401 - fixtures
from tests.test_auth_signin import consent, csrf, post, scalar

PICTURE = "https://lh3.googleusercontent.com/a/ada-photo=s96-c"


def browser_for(new_browser, uid):
    b = new_browser()
    assert b.post(f"/test/login/{uid}").status_code == 200
    b.headers.update(csrf(b))
    return b


@pytest.fixture
def ada(new_browser, pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    return browser_for(new_browser, uid), uid


@pytest.fixture(autouse=True)
def _clean(request):
    yield
    if "pg_engine" in request.fixturenames:
        from tests.conftest import TABLES
        with request.getfixturevalue("pg_engine").begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES}, user_avatars CASCADE"))


def image(fmt="PNG", size=(400, 300), exif: bytes | None = None) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt, **({"exif": exif} if exif else {}))
    return out.getvalue()


def parsed(b):
    return b.post("/api/resume/parse", files={"file": ("r.txt", fixture_text("resume_analyst.txt"))}).json()


# --- normalizing pictures ------------------------------------------------------------------------


def test_normalize_crops_resizes_and_reencodes():
    data = avatars.normalize(image())
    with Image.open(io.BytesIO(data)) as out:
        assert (out.format, out.size) == ("WEBP", (256, 256))


def test_normalize_drops_exif():
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    data = avatars.normalize(image("JPEG", exif=exif.tobytes()))
    with Image.open(io.BytesIO(data)) as out:
        assert not out.getexif()
    assert b"SecretCam" not in data


@pytest.mark.parametrize("raw,code", [
    (b"", "empty"), (b"not an image at all", "unsupported_type"), (b"x" * (2 * 1024 * 1024 + 1), "too_large"),
])
def test_normalize_refuses(raw, code):
    with pytest.raises(avatars.BadImage, match=code):
        avatars.normalize(raw)


def test_normalize_refuses_huge_dimensions():
    with pytest.raises(avatars.BadImage, match="too_large"):
        avatars.normalize(image(size=(6000, 6000)))


@pytest.mark.parametrize("url,ok", [
    (PICTURE, True), ("https://avatars.githubusercontent.com/u/4242?v=4", True),
    ("http://lh3.googleusercontent.com/a/x", False), ("https://evil.example/a.png", False),
    ("https://googleusercontent.com.evil.example/a", False), ("https://user@lh3.googleusercontent.com/a", False),
    ("https://lh3.googleusercontent.com:8443/a", False), ("https://169.254.169.254/latest", False), (None, False),
])
def test_provider_picture_hosts_are_allowlisted(url, ok):
    assert avatars.provider_picture_ok(url) is ok


# --- uploading, serving, removing ----------------------------------------------------------------


def test_upload_serve_and_remove(ada, new_browser, pg_engine):
    b, uid = ada
    res = b.put("/api/profile/avatar", files={"file": ("me.png", image(), "image/png")})
    assert res.status_code == 200 and res.json()["avatar_source"] == "upload"
    url = res.json()["avatar_url"]
    assert url.startswith("/api/profile/avatar?v=") and b.get("/api/me").json()["avatar_url"] == url
    pic = b.get("/api/profile/avatar")
    assert pic.headers["content-type"] == "image/webp" and pic.headers["cache-control"].startswith("private")
    assert pic.headers["x-content-type-options"] == "nosniff"

    eve = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    assert eve.get("/api/profile/avatar").status_code == 404  # only ever your own

    out = b.delete("/api/profile/avatar").json()
    assert out["avatar_url"] is None and b.get("/api/profile/avatar").status_code == 404
    assert scalar(pg_engine, "SELECT avatar_removed_at IS NOT NULL FROM users WHERE id = :u", u=uid)


def test_upload_refuses_bad_files(ada):
    b, _ = ada
    res = b.put("/api/profile/avatar", files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")})
    assert (res.status_code, res.json()["detail"]) == (415, "avatar_unsupported_type")
    res = b.put("/api/profile/avatar", files={"file": ("big.png", b"x" * (2 * 1024 * 1024 + 10), "image/png")})
    assert (res.status_code, res.json()["detail"]) == (413, "avatar_too_large")


def test_avatar_size_is_enforced_by_the_database(pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    with pytest.raises(Exception, match="ck_user_avatars_size"), pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO user_avatars (user_id, content_type, data, sha256, source)"
                          " VALUES (:u, 'image/webp', :d, 'x', 'upload')"), {"u": uid, "d": b"x" * 262_145})


# --- provider pictures -------------------------------------------------------------------------


def google_user(pg_engine, sub="g-123"):
    uid = make_user(pg_engine, "new.person@example.com")
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO accounts (user_id, provider, provider_account_id, email_at_link)"
                          " VALUES (:u, 'google', :s, 'new.person@example.com')"), {"u": uid, "s": sub})
    return uid


def test_google_sign_in_imports_the_picture_once(client, mock, pg_engine):
    uid = google_user(pg_engine)
    route = mock.get(PICTURE.split("?")[0]).respond(content=image("JPEG"), headers={"content-type": "image/jpeg"})
    assert where(google(client, mock, picture=PICTURE)) == "/app"
    assert scalar(pg_engine, "SELECT source FROM user_avatars WHERE user_id = :u", u=uid) == "provider"
    assert len(route.calls) == 1
    google(client, mock, picture=PICTURE)  # already has one: not fetched again
    assert len(route.calls) == 1


def test_a_removed_picture_stays_removed(client, mock, pg_engine):
    uid = google_user(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE users SET avatar_removed_at = now() WHERE id = :u"), {"u": uid})
    route = mock.get(PICTURE.split("?")[0]).respond(content=image())
    assert where(google(client, mock, picture=PICTURE)) == "/app"
    assert route.calls == [] and scalar(pg_engine, "SELECT count(*) FROM user_avatars") == 0


def test_a_bad_picture_never_breaks_sign_in(client, mock, pg_engine):
    uid = google_user(pg_engine)
    mock.get(PICTURE.split("?")[0]).respond(content=b"<html>not an image</html>")
    assert where(google(client, mock, picture=PICTURE)) == "/app"
    assert scalar(pg_engine, "SELECT count(*) FROM auth_sessions WHERE user_id = :u", u=uid) == 1
    assert scalar(pg_engine, "SELECT count(*) FROM user_avatars") == 0


def test_pictures_from_other_hosts_are_never_fetched(client, mock, pg_engine):
    google_user(pg_engine)
    evil = mock.get("https://evil.example/a.png").respond(content=image())
    assert where(google(client, mock, picture="https://evil.example/a.png")) == "/app"
    assert evil.calls == [] and scalar(pg_engine, "SELECT count(*) FROM user_avatars") == 0


def test_new_sign_up_gets_the_picture_when_the_account_is_made(client, mock, notices, make_invite, pg_engine):
    route = mock.get(PICTURE.split("?")[0]).respond(content=image())
    assert where(google(client, mock, picture=PICTURE)) == "/signup/invite"
    assert scalar(pg_engine, "SELECT picture_url FROM pending_auth") == PICTURE
    assert route.calls == []  # nothing fetched before there's an account
    post(client, "/api/auth/signup/invite", {"code": make_invite()})
    assert post(client, "/api/auth/signup/complete", consent(notices)).json() == {"next": "signed_in"}
    assert scalar(pg_engine, "SELECT source FROM user_avatars") == "provider" and len(route.calls) == 1


def test_pending_sign_up_drops_a_picture_from_an_unknown_host(client, mock, pg_engine):
    assert where(google(client, mock, picture="https://evil.example/a.png")) == "/signup/invite"
    assert scalar(pg_engine, "SELECT picture_url FROM pending_auth") is None


# --- phone ---------------------------------------------------------------------------------------


def test_phone_is_optional_and_normalized(ada):
    b, _ = ada
    assert b.patch("/api/profile", json={"phone": "+91 98765-43210"}).json()["phone"] == "+919876543210"
    assert b.patch("/api/profile", json={"name": "Ada"}).json()["phone"] == "+919876543210"  # untouched
    assert b.patch("/api/profile", json={"phone": None}).json()["phone"] is None
    assert b.patch("/api/profile", json={"phone": "98765"}).status_code == 422
    assert b.patch("/api/profile", json={"name": None}).status_code == 422


# --- saved resume versions ---------------------------------------------------------------------


def save(b, resume, **kw):
    return b.post("/api/resumes", json={"resume": resume, "source": "paste", **kw}).json()


def test_edits_become_versions_and_old_ones_stay_readable(ada):
    b, _ = ada
    resume = parsed(b)
    rid = save(b, resume)["id"]
    edited = json.loads(json.dumps(resume))
    edited["summary"] = "Analyst who ships."
    entry = edited["sections"][0]["entries"][0]
    entry["bullets"].append({"id": f"{entry['id']}.b99", "text": "Added a new line."})
    res = b.post(f"/api/resumes/{rid}/versions", json={"resume": edited, "source": "edit"})
    assert res.status_code == 201 and (res.json()["version"], res.json()["shown_version"]) == (2, 2)
    assert [v["version"] for v in b.get(f"/api/resumes/{rid}/versions").json()] == [2, 1]
    assert b.get(f"/api/resumes/{rid}").json()["resume"]["summary"] == "Analyst who ships."
    old = b.get(f"/api/resumes/{rid}", params={"version": 1}).json()
    assert old["shown_version"] == 1 and old["resume"]["summary"] == resume["summary"]
    assert b.get(f"/api/resumes/{rid}", params={"version": 9}).status_code == 404


def test_edits_keep_bullet_ids_tied_to_their_entry(ada):
    b, _ = ada
    resume = parsed(b)
    rid = save(b, resume)["id"]
    bad = json.loads(json.dumps(resume))
    first, second = bad["sections"][0]["entries"][0], bad["sections"][0]["entries"][1]
    second["bullets"].append({"id": f"{first['id']}.b77", "text": "moved"})
    res = b.post(f"/api/resumes/{rid}/versions", json={"resume": bad, "source": "edit"})
    assert (res.status_code, res.json()["detail"]) == (422, "bullet_id_mismatch")


def test_replacement_upload_is_a_new_version(ada):
    b, _ = ada
    rid = save(b, parsed(b))["id"]
    res = b.post(f"/api/resumes/{rid}/versions", json={"resume": parsed(b), "source": "upload", "file_name": "v2.pdf"})
    assert res.json()["source"] == "upload"
    assert b.get(f"/api/resumes/{rid}/versions").json()[0]["file_name"] == "v2.pdf"


def test_rename_default_duplicate_delete(ada):
    b, _ = ada
    resume = parsed(b)
    a, c = save(b, resume, title="A")["id"], save(b, resume, title="C")["id"]
    assert b.patch(f"/api/resumes/{c}", json={"title": "Consulting", "is_default": True}).json()["is_default"]
    listed = {r["id"]: r for r in b.get("/api/resumes").json()}
    assert (listed[c]["title"], listed[c]["is_default"], listed[a]["is_default"]) == ("Consulting", True, False)
    copy = b.post(f"/api/resumes/{c}/duplicate").json()
    assert copy["title"] == "Consulting (copy)" and copy["is_default"] is False
    assert b.delete(f"/api/resumes/{c}").status_code == 204  # the default: another takes over
    remaining = b.get("/api/resumes").json()
    assert len(remaining) == 2 and sum(r["is_default"] for r in remaining) == 1


# --- tailorings ----------------------------------------------------------------------------------


def tailoring(b):
    resume = parsed(b)
    jd = b.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    aid = b.post("/api/analyses", json={"resume": resume, "jd": jd}).json()["analysis_id"]
    b.post("/api/tailor", json={"resume": resume, "jd": jd, "use_llm": False}, headers={"X-Analysis-Id": aid})
    return aid


def test_tailorings_list_detail_and_paging(ada):
    b, _ = ada
    ids = [tailoring(b) for _ in range(3)]
    first = b.get("/api/tailorings", params={"limit": 2}).json()
    assert [t["id"] for t in first["items"]] == ids[::-1][:2] and first["next_before"]
    rest = b.get("/api/tailorings", params={"limit": 2, "before": first["next_before"]}).json()
    assert [t["id"] for t in rest["items"]] == [ids[0]] and rest["next_before"] is None
    detail = b.get(f"/api/tailorings/{ids[0]}").json()
    assert detail["status"] == "tailored" and detail["content_available"] and detail["tailored"]["bullets"]
    assert b.get("/api/tailorings", params={"before": "garbage"}).status_code == 422


def test_deleting_a_tailoring_clears_its_text_but_keeps_the_count(ada, pg_engine):
    b, uid = ada
    aid = tailoring(b)
    allowance = b.get("/api/analyses/allowance").json()["free_used"]
    assert b.delete(f"/api/tailorings/{aid}").status_code == 204
    row = scalar(pg_engine, "SELECT row_to_json(a) FROM analyses a WHERE id = :a", a=aid)
    assert row["resume"] is None and row["tailored"] is None and row["deleted_at"] and row["purged_at"]
    assert b.get(f"/api/tailorings/{aid}").status_code == 404
    assert b.get("/api/tailorings").json()["items"] == []
    assert b.get("/api/dashboard").json()["recent"] == []
    assert b.get("/api/analyses/allowance").json()["free_used"] == allowance  # still counts
    assert b.delete(f"/api/tailorings/{aid}").status_code == 404


# --- consents and export -----------------------------------------------------------------------


def test_consent_history_and_research_toggle(new_browser, notices, outbox, make_invite, pg_engine):
    from tests.test_auth_signin import sign_up
    b = new_browser()
    sign_up(b, outbox, notices, make_invite())
    b.headers.update(csrf(b))
    first = b.get("/api/account/consents").json()
    assert first["research"] is False and first["research_available"] is True
    assert {h["purpose"] for h in first["history"]} == {"service", "age_18_plus"}
    on = b.put("/api/account/consents/research", json={"granted": True}).json()
    assert on["research"] is True and on["history"][0]["method"] == "account_settings"
    again = b.put("/api/account/consents/research", json={"granted": True}).json()
    assert len(again["history"]) == len(on["history"])  # no duplicate record
    off = b.put("/api/account/consents/research", json={"granted": False}).json()
    assert off["research"] is False and off["history"][0]["action"] == "withdrawn"


def test_export_has_my_data_and_nobody_elses(ada, new_browser, pg_engine):
    b, uid = ada
    resume = parsed(b)
    save(b, resume, title="Mine")
    tailoring(b)
    b.put("/api/profile/preferences", json={"target_roles": ["Analyst"]})
    b.put("/api/profile/avatar", files={"file": ("me.png", image(), "image/png")})
    eve = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    eve.headers.update(csrf(eve))
    save(eve, resume, title="Eve's")

    res = b.post("/api/account/export")
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    assert res.headers["cache-control"] == "no-store"
    doc = res.json()
    assert doc["account"]["email"] == "ada@example.com"
    assert [r["title"] for r in doc["saved_resumes"]] == ["Mine"]
    assert doc["saved_resumes"][0]["versions"][0]["content"]["sections"] == resume["sections"]
    assert len(doc["tailorings"]) == 1 and doc["tailorings"][0]["tailored"]
    assert doc["job_preferences"]["target_roles"] == ["Analyst"] and doc["picture"]["data_base64"]
    blob = json.dumps(doc)
    assert "eve@example.com" not in blob and "Eve's" not in blob
    for secret in ("token_hash", "session_token", "ip_hmac", "subject_ref"):
        assert secret not in blob


def test_export_needs_csrf(new_browser, pg_engine):
    uid = make_user(pg_engine, "ada@example.com")
    b = new_browser()
    b.post(f"/test/login/{uid}")
    assert b.post("/api/account/export").status_code == 403


def test_account_deletion_removes_picture_and_phone(ada, pg_engine):
    b, uid = ada
    b.put("/api/profile/avatar", files={"file": ("me.png", image(), "image/png")})
    b.patch("/api/profile", json={"phone": "+14155550100"})
    assert b.post("/api/account/delete", json={"confirm": True}).status_code == 204
    assert scalar(pg_engine, "SELECT count(*) FROM user_avatars WHERE user_id = :u", u=uid) == 0
    assert scalar(pg_engine, "SELECT phone FROM users WHERE id = :u", u=uid) is None


# --- isolation ---------------------------------------------------------------------------------


def test_user_a_cannot_touch_user_bs_resumes_or_tailorings(new_browser, pg_engine):
    a = browser_for(new_browser, make_user(pg_engine, "ada@example.com"))
    e = browser_for(new_browser, make_user(pg_engine, "eve@example.com"))
    resume = parsed(a)
    rid = save(a, resume)["id"]
    aid = tailoring(a)
    for method, path, body in [
        ("GET", f"/api/resumes/{rid}", None), ("GET", f"/api/resumes/{rid}/versions", None),
        ("POST", f"/api/resumes/{rid}/versions", {"resume": resume, "source": "paste"}),
        ("PATCH", f"/api/resumes/{rid}", {"title": "pwned"}), ("POST", f"/api/resumes/{rid}/duplicate", None),
        ("DELETE", f"/api/resumes/{rid}", None), ("GET", f"/api/tailorings/{aid}", None),
        ("DELETE", f"/api/tailorings/{aid}", None),
    ]:
        assert e.request(method, path, json=body).status_code == 404, (method, path)
    assert e.get("/api/tailorings").json()["items"] == []
    assert a.get(f"/api/resumes/{rid}").json()["title"] != "pwned"
    assert a.get(f"/api/tailorings/{aid}").status_code == 200

