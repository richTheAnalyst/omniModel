"""Our own sign-in: register, log in, sign out everywhere. Plain Python plus SQL, no web code.
api/auth_routes.py turns these into endpoints.

How it keeps people safe
  * Passwords are never stored. Only a salted scrypt hash is (a slow, memory-hungry hash made for passwords).
  * Wrong email and wrong password give the same answer, and take about the same time.
  * 5 wrong passwords in a row lock that account for 15 minutes.
  * A login token is signed with AUTH_SECRET, lasts 7 days, and is cancelled by "sign out everywhere".
What it does not do (yet): email verification, password reset by email, or limiting how many accounts one person can create.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from . import accounts, db

MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8
MAX_PASSWORD = 128
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
_SCRYPT_MAXMEM = 128 * 1024 * 1024
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BadInput(Exception):        # becomes HTTP 422
    pass


class Conflict(Exception):        # becomes HTTP 409
    pass


class Unauthorized(Exception):    # becomes HTTP 401
    pass


class Locked(Exception):          # becomes HTTP 429
    pass


class RegisterIn(BaseModel):
    name: str = Field(max_length=300)
    email: str = Field(max_length=400)
    password: str = Field(max_length=1000)


class LoginIn(BaseModel):
    email: str = Field(max_length=400)
    password: str = Field(max_length=1000)


# ---------------------------------------------------------------- passwords
def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=_SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """True only if the password matches. Any malformed stored value is simply 'no'."""
    try:
        scheme, n, r, p, salt, digest = (stored or "").split("$")
        if scheme != "scrypt" or int(n) > 2 ** 20:
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                maxmem=_SCRYPT_MAXMEM, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_dummy: str | None = None


def _dummy_hash() -> str:
    """Checked against when the email is unknown, so an unknown email costs the same time as a wrong password."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password("not-a-real-password")
    return _dummy


# ---------------------------------------------------------------- checking input
def clean_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise BadInput("Enter a valid email address.")
    return email


def clean_name(value: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise BadInput("Enter your name.")
    if len(name) > 100:
        raise BadInput("Use a shorter name (100 characters at most).")
    return name


def check_password(password: str, email: str = "") -> None:
    if len(password or "") < MIN_PASSWORD:
        raise BadInput(f"Use at least {MIN_PASSWORD} characters for the password.")
    if len(password) > MAX_PASSWORD:
        raise BadInput(f"Use at most {MAX_PASSWORD} characters for the password.")
    if email and password.strip().lower() == email:
        raise BadInput("The password must not be your email address.")


def _session(subject: str, token_version: int) -> dict:
    me = accounts.load_account({"sub": subject, "_local": True, "tv": token_version})
    token, expires = accounts.issue_token(subject, token_version)
    return {"token": token, "expires_at": expires.isoformat(), "me": me}


# ---------------------------------------------------------------- register, log in, sign out
def register(data: RegisterIn) -> dict:
    name, email = clean_name(data.name), clean_email(data.email)
    check_password(data.password, email)
    hashed = hash_password(data.password)           # slow on purpose, so it is done before the database is touched
    subject = "local:" + str(uuid.uuid4())
    duplicate = Conflict("An account with this email already exists. Try signing in instead.")
    try:
        with db.connection() as conn:
            if conn.execute("select 1 as x from users where lower(email) = %s and password_hash is not null",
                            (email,)).fetchone():
                raise duplicate
            user = conn.execute(
                """insert into users (auth_subject, email, display_name, password_hash, last_seen_at)
                   values (%s, %s, %s, %s, now()) returning token_version""",
                (subject, email, name, hashed),
            ).fetchone()
    except Conflict:
        raise
    except Exception as exc:
        if type(exc).__name__ == "UniqueViolation":   # two sign-ups for the same email at the very same moment
            raise duplicate from None
        raise
    return _session(subject, user["token_version"])


def login(data: LoginIn) -> dict:
    try:
        email = clean_email(data.email)
    except BadInput:
        raise Unauthorized("Incorrect email or password.") from None
    with db.connection() as conn:
        user = conn.execute(
            """select id, auth_subject, password_hash, token_version, locked_until,
                      coalesce(locked_until > now(), false) as locked,
                      coalesce(ceil(extract(epoch from (locked_until - now())) / 60), 0) as wait_minutes
               from users where lower(email) = %s and password_hash is not null""",
            (email,),
        ).fetchone()
    if user is None:
        verify_password(data.password, _dummy_hash())
        raise Unauthorized("Incorrect email or password.")
    if user["locked"]:
        minutes = max(1, int(user["wait_minutes"]))
        raise Locked(f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}.")
    ok = verify_password(data.password, user["password_hash"])
    with db.connection() as conn:
        if ok:
            conn.execute("update users set failed_logins = 0, locked_until = null where id = %s", (user["id"],))
        else:
            # A lock that has run out starts the count again at 1; otherwise add one. Reaching the limit locks.
            conn.execute(
                """update users set
                     failed_logins = case when locked_until is not null and locked_until <= now() then 1 else failed_logins + 1 end,
                     locked_until = case when (case when locked_until is not null and locked_until <= now()
                                                    then 1 else failed_logins + 1 end) >= %s
                                         then now() + make_interval(mins => %s) else null end
                   where id = %s""",
                (MAX_FAILED, LOCK_MINUTES, user["id"]),
            )
    if not ok:
        raise Unauthorized("Incorrect email or password.")
    return _session(user["auth_subject"], user["token_version"])


def sign_out_everywhere(claims: dict) -> dict:
    """Cancels every login token this user has, on every device, including the one making the request."""
    if not claims.get("_local"):
        raise BadInput("This sign-in is managed by another provider.")
    with db.connection() as conn:
        row = conn.execute(
            "update users set token_version = token_version + 1 where auth_subject = %s returning id", (claims["sub"],)
        ).fetchone()
    if row is None:
        raise accounts.SessionExpired("Your session has ended. Please sign in again.")
    return {"signed_out": True}