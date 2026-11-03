"""Our own sign-in. The first group needs no database; the rest need TEST_DATABASE_URL (see conftest.py)."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from omnimodel import accounts, db, local_auth, tracking
from omnimodel.local_auth import LoginIn, RegisterIn

SECRET = "x" * 40


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", SECRET)
    monkeypatch.delenv("AUTH_JWKS_URL", raising=False)
    monkeypatch.setattr(local_auth, "SCRYPT_N", 2 ** 10)   # fast hashing for tests; the real strength is checked below
    local_auth._dummy = None


def new_user(prefix="ama", password="correct horse battery"):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@Example.com"
    out = local_auth.register(RegisterIn(name=f"{prefix.title()} Mensah", email=email, password=password))
    return email, password, out


def sign_in(email, password):
    return local_auth.login(LoginIn(email=email, password=password))


# ------------------------------------------------------------------ no database needed
def test_real_hashing_strength_and_format(monkeypatch):
    monkeypatch.undo()                                      # back to the production settings
    assert local_auth.SCRYPT_N >= 2 ** 14 and local_auth.SCRYPT_R >= 8
    stored = local_auth.hash_password("pässword with spaces")
    assert stored.startswith("scrypt$") and "pässword" not in stored
    assert local_auth.verify_password("pässword with spaces", stored)
    assert not local_auth.verify_password("pässword with space", stored)


def test_hash_is_salted_and_verify_handles_garbage():
    a, b = local_auth.hash_password("same password"), local_auth.hash_password("same password")
    assert a != b
    assert local_auth.verify_password("same password", a) and local_auth.verify_password("same password", b)
    for junk in (None, "", "plain", "scrypt$1$2", "scrypt$x$8$1$AA==$AA==", "md5$1$2$3$4$5", "scrypt$99999999$8$1$AA==$AA=="):
        assert local_auth.verify_password("same password", junk) is False


@pytest.mark.parametrize("raw,expected", [("  Ama@Example.COM ", "ama@example.com"), ("a.b+c@sub.example.org", "a.b+c@sub.example.org")])
def test_clean_email_ok(raw, expected):
    assert local_auth.clean_email(raw) == expected


@pytest.mark.parametrize("bad", ["", "no-at-sign", "two@@example.com", "a b@example.com", "a@nodot", "@example.com", "a@" + "x" * 260 + ".com"])
def test_clean_email_rejects(bad):
    with pytest.raises(local_auth.BadInput):
        local_auth.clean_email(bad)


def test_name_and_password_rules():
    assert local_auth.clean_name("  Ama   Mensah ") == "Ama Mensah"
    for bad in ("", "   ", "x" * 101):
        with pytest.raises(local_auth.BadInput):
            local_auth.clean_name(bad)
    local_auth.check_password("12345678")
    for bad, email in (("short", ""), ("x" * 129, ""), ("ama@example.com", "ama@example.com"), ("  AMA@example.com ", "ama@example.com")):
        with pytest.raises(local_auth.BadInput):
            local_auth.check_password(bad, email)


def test_token_round_trip_and_claims():
    token, expires = accounts.issue_token("local:abc", 3)
    claims = accounts.verify_token(token)
    assert claims["sub"] == "local:abc" and claims["tv"] == 3 and claims["_local"] is True
    assert timedelta(days=6) < expires - datetime.now(timezone.utc) <= timedelta(days=7, minutes=1)


def _forge(secret=SECRET, alg="HS256", **over):
    claims = {"sub": "local:abc", "tv": 0, "iss": accounts.LOCAL_ISSUER, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm=alg)


def test_bad_tokens_are_rejected():
    assert accounts.verify_token(_forge())["sub"] == "local:abc"            # the control: a well-formed one passes
    cases = {
        "wrong secret": _forge(secret="y" * 40),
        "expired": _forge(exp=datetime.now(timezone.utc) - timedelta(hours=1)),
        "wrong issuer": _forge(iss="someone-else"),
        "no issuer": _forge(iss=None),
        "no tv": _forge(tv=None),
        "no sub": _forge(sub=None),
        "other hmac size": _forge(alg="HS512"),
        "not a token": "abc.def.ghi",
    }
    for label, token in cases.items():
        with pytest.raises(ValueError):
            accounts.verify_token(token)
            pytest.fail(f"accepted: {label}")
    unsigned = jwt.encode({"sub": "local:abc", "tv": 0, "iss": accounts.LOCAL_ISSUER, "exp": time.time() + 3600}, None, algorithm="none")
    with pytest.raises(ValueError):
        accounts.verify_token(unsigned)


def test_token_cannot_claim_to_be_local_for_itself():
    claims = accounts.verify_token(_forge(_local=False))
    assert claims["_local"] is True                                         # set by the server after checking, not by the token


def test_accounts_off_without_a_long_secret(monkeypatch):
    token = _forge()
    monkeypatch.setenv("AUTH_SECRET", "too short")
    assert accounts.enabled() is False
    with pytest.raises(ValueError):
        accounts.verify_token(token)
    monkeypatch.delenv("AUTH_SECRET")
    with pytest.raises(RuntimeError):
        accounts.issue_token("local:abc", 0)


def test_check_session_rules():
    accounts.check_session({"_local": True, "tv": 2}, 2)
    for tv in (1, 3, None):
        with pytest.raises(accounts.SessionExpired):
            accounts.check_session({"_local": True, "tv": 2}, tv)
    accounts.check_session({"sub": "provider-user"}, 7)                     # outside-provider tokens have no tv


# ------------------------------------------------------------------ with a database
def test_register_then_login_and_me(database):
    email, password, out = new_user()
    assert out["token"] and out["me"]["user"]["email"] == email.lower() and out["me"]["workspaces"][0]["role"] == "owner"
    claims = accounts.verify_token(out["token"])
    assert accounts.load_account(claims)["user"]["id"] == out["me"]["user"]["id"]
    again = sign_in(email.upper(), password)                                # email is not case sensitive
    assert again["me"]["user"]["id"] == out["me"]["user"]["id"]
    assert again["me"]["active_workspace_id"] == out["me"]["active_workspace_id"]   # one business, not a new one each login
    with db.connection() as conn:
        row = conn.execute("select password_hash from users where lower(email) = %s", (email.lower(),)).fetchone()
    assert password not in row["password_hash"] and row["password_hash"].startswith("scrypt$")


def test_duplicate_email_is_refused_any_case(database):
    email, _, _ = new_user()
    with pytest.raises(local_auth.Conflict):
        local_auth.register(RegisterIn(name="Other", email=email.upper(), password="another password"))


def test_two_sign_ups_at_the_same_moment_make_one_account(database):
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    results, barrier = [], threading.Barrier(2)

    def go():
        barrier.wait()
        try:
            local_auth.register(RegisterIn(name="Race", email=email, password="racing password"))
            results.append("ok")
        except local_auth.Conflict:
            results.append("conflict")

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["conflict", "ok"]
    with db.connection() as conn:
        assert conn.execute("select count(*) as n from users where lower(email) = %s", (email,)).fetchone()["n"] == 1


def test_wrong_password_and_unknown_email_look_the_same(database):
    email, _, _ = new_user()
    with pytest.raises(local_auth.Unauthorized) as wrong:
        sign_in(email, "not the password")
    with pytest.raises(local_auth.Unauthorized) as unknown:
        sign_in("nobody-here@example.com", "not the password")
    with pytest.raises(local_auth.Unauthorized) as malformed:
        sign_in("not an email", "whatever you like")
    assert str(wrong.value) == str(unknown.value) == str(malformed.value) == "Incorrect email or password."


def test_lockout_after_five_wrong_passwords(database):
    email, password, _ = new_user()
    for _ in range(local_auth.MAX_FAILED - 1):
        with pytest.raises(local_auth.Unauthorized):
            sign_in(email, "wrong password!")
    with pytest.raises(local_auth.Unauthorized):                            # the 5th wrong one locks it
        sign_in(email, "wrong password!")
    with pytest.raises(local_auth.Locked) as locked:                        # now even the right password is refused
        sign_in(email, password)
    assert "minute" in str(locked.value)
    with pytest.raises(local_auth.Locked):                                  # and trying more does not extend the lock
        sign_in(email, "wrong password!")
    with db.connection() as conn:
        row = conn.execute("select failed_logins, locked_until is not null as locked from users where lower(email) = %s", (email.lower(),)).fetchone()
        assert row["failed_logins"] == 5 and row["locked"] is True
        conn.execute("update users set locked_until = now() - interval '1 minute' where lower(email) = %s", (email.lower(),))
    assert sign_in(email, password)["token"]                                # the lock ran out
    with db.connection() as conn:
        row = conn.execute("select failed_logins, locked_until is not null as locked from users where lower(email) = %s", (email.lower(),)).fetchone()
    assert row["failed_logins"] == 0 and row["locked"] is False


def test_after_a_lock_runs_out_one_mistake_does_not_lock_again(database):
    email, password, _ = new_user()
    for _ in range(local_auth.MAX_FAILED):
        with pytest.raises(local_auth.Unauthorized):
            sign_in(email, "wrong password!")
    with db.connection() as conn:
        conn.execute("update users set locked_until = now() - interval '1 minute' where lower(email) = %s", (email.lower(),))
    with pytest.raises(local_auth.Unauthorized):                            # a plain wrong password, not Locked
        sign_in(email, "wrong password!")
    assert sign_in(email, password)["token"]


def test_good_login_resets_the_count(database):
    email, password, _ = new_user()
    for _ in range(local_auth.MAX_FAILED - 1):
        with pytest.raises(local_auth.Unauthorized):
            sign_in(email, "wrong password!")
    assert sign_in(email, password)["token"]
    for _ in range(local_auth.MAX_FAILED - 1):                              # four more mistakes still do not lock
        with pytest.raises(local_auth.Unauthorized):
            sign_in(email, "wrong password!")
    assert sign_in(email, password)["token"]


def test_sign_out_everywhere_kills_old_tokens_but_not_new_logins(database):
    email, password, out = new_user()
    old = accounts.verify_token(out["token"])
    accounts.load_account(old)                                              # fine before
    ctx_before = tracking.resolve_member(old)
    assert local_auth.sign_out_everywhere(old) == {"signed_out": True}
    with pytest.raises(accounts.SessionExpired):
        accounts.load_account(old)
    with pytest.raises(accounts.SessionExpired):
        tracking.resolve_member(old)
    fresh = sign_in(email, password)
    claims = accounts.verify_token(fresh["token"])
    assert accounts.load_account(claims)["user"]["email"] == email.lower()
    assert tracking.resolve_member(claims) == ctx_before                    # same business as before


def test_token_of_a_deleted_user_does_not_bring_them_back(database):
    email, _, out = new_user()
    claims = accounts.verify_token(out["token"])
    with db.connection() as conn:
        conn.execute("delete from users where lower(email) = %s", (email.lower(),))
    for call in (lambda: accounts.load_account(claims), lambda: tracking.resolve_member(claims)):
        with pytest.raises(accounts.SessionExpired):
            call()
    with db.connection() as conn:
        assert conn.execute("select count(*) as n from users where auth_subject = %s", (claims["sub"],)).fetchone()["n"] == 0


def test_sign_out_everywhere_refuses_outside_provider_tokens(database):
    with pytest.raises(local_auth.BadInput):
        local_auth.sign_out_everywhere({"sub": "provider-user"})


def test_a_signed_in_user_can_save_and_track_a_lead(database):
    _, _, out = new_user()
    ctx = tracking.resolve_member(accounts.verify_token(out["token"]))
    saved = tracking.save_lead(ctx, tracking.SaveLead(place_id="p-1", name="Acme"))["lead"]
    tracking.log_event(ctx, saved["id"], tracking.EventIn(type="call_attempt"))
    assert tracking.get_lead(ctx, saved["id"])["lead"]["status"] == "contacted"
    _, _, other = new_user("kofi")
    other_ctx = tracking.resolve_member(accounts.verify_token(other["token"]))
    assert other_ctx.workspace_id != ctx.workspace_id and tracking.list_leads(other_ctx)["total"] == 0