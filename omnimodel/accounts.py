"""Accounts. A guest has no token and keeps using the shared API key. A signed-in user sends
`Authorization: Bearer <token>` and the server checks the token before trusting it.

Two kinds of token are understood:
  * Our own (HS256), issued by /auth/login and /auth/register (see local_auth.py). Needs AUTH_SECRET.
  * Optionally, a token from an outside sign-in provider (Clerk, Auth0, Firebase...), checked against that provider's
    public keys (JWKS). Needs AUTH_JWKS_URL. Leave it empty if you only use our own sign-in.

Environment variables
  AUTH_SECRET     turns our own sign-in on: a long random string (32+ characters) that signs login tokens.
                  Make one with:  python -c "import secrets; print(secrets.token_urlsafe(48))"
                  Keep it secret and never change it casually: changing it signs everyone out.
  AUTH_JWKS_URL   optional: an outside provider's public key list (ends in jwks.json or similar)
  AUTH_ISSUER     optional, outside provider only: if set, the token's issuer must match
  AUTH_AUDIENCE   optional, outside provider only: if set, the token's audience must match
  DATABASE_URL    needed for /me and everything saved to the database
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from jwt import PyJWKClient

from . import db

ALGORITHMS = ["EdDSA", "RS256", "ES256"]   # outside providers: asymmetric only, so a public key can never be used as a secret
LOCAL_ISSUER = "omnimodel"
TOKEN_DAYS = 7
_jwks: PyJWKClient | None = None


class SessionExpired(ValueError):
    """The token is genuine but no longer good: the user was deleted or signed out everywhere. Becomes HTTP 401."""


def local_enabled() -> bool:
    return len(os.getenv("AUTH_SECRET", "")) >= 32


def jwks_enabled() -> bool:
    return bool(os.getenv("AUTH_JWKS_URL"))


def enabled() -> bool:
    return local_enabled() or jwks_enabled()


def bearer_token(authorization: str | None) -> str | None:
    """Pulls the token out of an 'Authorization: Bearer <token>' header."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() else None


def _secret() -> str:
    secret = os.getenv("AUTH_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("AUTH_SECRET must be set to a random string of at least 32 characters.")
    return secret


def issue_token(subject: str, token_version: int) -> tuple[str, datetime]:
    """A signed login token for one of our own users, and when it expires."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=TOKEN_DAYS)
    claims = {"sub": subject, "tv": int(token_version), "iss": LOCAL_ISSUER, "iat": now, "exp": expires}
    return jwt.encode(claims, _secret(), algorithm="HS256"), expires


def _client() -> PyJWKClient:
    global _jwks
    url = os.getenv("AUTH_JWKS_URL")
    if _jwks is None or _jwks.uri != url:
        _jwks = PyJWKClient(url, cache_keys=True, lifespan=3600)   # keys are cached for an hour
    return _jwks


def verify_token(token: str) -> dict:
    """Returns the token's claims, or raises ValueError with a reason. Never trusts a token it cannot verify.
    The signing method is chosen here, never by the token: our own tokens must be HS256 signed with AUTH_SECRET and
    carry our issuer; everything else must be an asymmetric token from the configured provider."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as exc:
        raise ValueError(f"Invalid token: {exc}")
    if alg == "HS256":
        if not local_enabled():
            raise ValueError("Accounts are not enabled on this server.")
        try:
            claims = jwt.decode(token, _secret(), algorithms=["HS256"], issuer=LOCAL_ISSUER, leeway=30,
                                options={"require": ["exp", "sub", "tv", "iss"], "verify_aud": False})
        except jwt.PyJWTError as exc:
            raise ValueError(f"Invalid token: {exc}")
        claims["_local"] = True     # set here, after checking: a token can never claim this for itself
        return claims
    if not jwks_enabled():
        raise ValueError("Accounts are not enabled on this server.")
    try:
        key = _client().get_signing_key_from_jwt(token).key
        options = {"require": ["exp", "sub"]}
        kwargs: dict = {}
        if os.getenv("AUTH_AUDIENCE"):
            kwargs["audience"] = os.getenv("AUTH_AUDIENCE")
        else:
            options["verify_aud"] = False
        if os.getenv("AUTH_ISSUER"):
            kwargs["issuer"] = os.getenv("AUTH_ISSUER")
        return jwt.decode(token, key, algorithms=ALGORITHMS, options=options, leeway=30, **kwargs)
    except jwt.PyJWTError as exc:
        raise ValueError(f"Invalid token: {exc}")


def check_session(claims: dict, token_version: int | None) -> None:
    """Our own tokens carry the user's token_version at login. Signing out everywhere raises the number in the
    database, which makes every older token stop working at once."""
    if claims.get("_local") and int(claims.get("tv", -1)) != int(token_version if token_version is not None else -2):
        raise SessionExpired("Your session has ended. Please sign in again.")


def load_account(claims: dict) -> dict:
    """Finds (or creates, on first sign-in) the user and their business workspace, and returns them.
    For our own tokens the user must already exist: a valid token for a deleted user does not bring them back."""
    sub = str(claims["sub"])
    local = bool(claims.get("_local"))
    with db.connection() as conn:
        conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (sub,))   # two quick requests must not create two workspaces
        if local:
            user = conn.execute(
                """update users set last_seen_at = now() where auth_subject = %s
                   returning id, email, display_name, token_version""", (sub,)).fetchone()
            if user is None:
                raise SessionExpired("Your session has ended. Please sign in again.")
            check_session(claims, user["token_version"])
        else:
            user = conn.execute(
                """insert into users (auth_subject, email, display_name, last_seen_at)
                   values (%s, %s, %s, now())
                   on conflict (auth_subject) do update
                     set email = coalesce(excluded.email, users.email),
                         display_name = coalesce(excluded.display_name, users.display_name),
                         last_seen_at = now()
                   returning id, email, display_name""",
                (sub, claims.get("email"), claims.get("name")),
            ).fetchone()
        workspaces = conn.execute(
            """select w.id, w.name, m.role
               from workspace_members m join workspaces w on w.id = m.workspace_id
               where m.user_id = %s order by m.created_at""",
            (user["id"],),
        ).fetchall()
        if not workspaces:                          # first sign-in: give them a business to work in
            email, name = user["email"], user["display_name"]
            label = f"{name or (email or 'My').split('@')[0]}'s business"
            ws = conn.execute("insert into workspaces (name) values (%s) returning id, name", (label,)).fetchone()
            conn.execute("insert into workspace_members (workspace_id, user_id, role) values (%s, %s, 'owner')", (ws["id"], user["id"]))
            workspaces = [{"id": ws["id"], "name": ws["name"], "role": "owner"}]
    return {
        "authenticated": True,
        "user": {"id": str(user["id"]), "email": user["email"], "name": user["display_name"]},
        "workspaces": [{"id": str(w["id"]), "name": w["name"], "role": w["role"]} for w in workspaces],
        "active_workspace_id": str(workspaces[0]["id"]),
    }