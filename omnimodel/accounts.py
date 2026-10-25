"""Optional accounts. A guest has no token and keeps using the shared API key. A signed-in user sends
`Authorization: Bearer <token>` and the server checks the token's signature against the sign-in provider's public keys (JWKS).
Works with any provider that issues JWTs (Neon Auth, Clerk, Auth0, Firebase, Google...).

Environment variables
  AUTH_JWKS_URL   required to turn accounts on: the provider's public key list (ends in jwks.json or similar)
  AUTH_ISSUER     optional: if set, the token's issuer must match
  AUTH_AUDIENCE   optional: if set, the token's audience must match
  DATABASE_URL    needed for /me and everything saved to the database
"""
from __future__ import annotations

import os

import jwt
from jwt import PyJWKClient

from . import db

ALGORITHMS = ["EdDSA", "RS256", "ES256"]
_jwks: PyJWKClient | None = None


def enabled() -> bool:
    return bool(os.getenv("AUTH_JWKS_URL"))


def bearer_token(authorization: str | None) -> str | None:
    """Pulls the token out of an 'Authorization: Bearer <token>' header."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() else None


def _client() -> PyJWKClient:
    global _jwks
    url = os.getenv("AUTH_JWKS_URL")
    if _jwks is None or _jwks.uri != url:
        _jwks = PyJWKClient(url, cache_keys=True, lifespan=3600)   # keys are cached for an hour
    return _jwks


def verify_token(token: str) -> dict:
    """Returns the token's claims, or raises ValueError with a reason. Never trusts a token it cannot verify."""
    if not enabled():
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


def load_account(claims: dict) -> dict:
    """Finds (or creates, on first sign-in) the user and their business workspace, and returns them."""
    sub, email, name = str(claims["sub"]), claims.get("email"), claims.get("name")
    with db.connection() as conn:
        conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (sub,))   # two quick requests must not create two workspaces
        user = conn.execute(
            """insert into users (auth_subject, email, display_name, last_seen_at)
               values (%s, %s, %s, now())
               on conflict (auth_subject) do update
                 set email = coalesce(excluded.email, users.email),
                     display_name = coalesce(excluded.display_name, users.display_name),
                     last_seen_at = now()
               returning id, email, display_name""",
            (sub, email, name),
        ).fetchone()
        workspaces = conn.execute(
            """select w.id, w.name, m.role
               from workspace_members m join workspaces w on w.id = m.workspace_id
               where m.user_id = %s order by m.created_at""",
            (user["id"],),
        ).fetchall()
        if not workspaces:                          # first sign-in: give them a business to work in
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