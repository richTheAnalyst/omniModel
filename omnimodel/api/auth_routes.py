"""Sign-up and sign-in endpoints. They need no API key: they are how a person gets a login token.

  POST /auth/register       {name, email, password}  ->  {token, expires_at, me}
  POST /auth/login          {email, password}        ->  {token, expires_at, me}
  POST /auth/logout-all     (needs a token)          ->  every login token this user has stops working

Send the token on later requests as  Authorization: Bearer <token>.  GET /me tells you who it belongs to.
Needs AUTH_SECRET (32+ random characters) and DATABASE_URL on the server."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from omnimodel import accounts, local_auth
from omnimodel.local_auth import LoginIn, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])

_DB_DOWN = {"OperationalError", "PoolTimeout", "InterfaceError"}   # the database cannot be reached (Neon may be waking up)


def _run(fn, *args):
    if not accounts.local_enabled():
        raise HTTPException(503, "Sign-in is not set up on this server yet (AUTH_SECRET is missing).")
    try:
        return fn(*args)
    except local_auth.BadInput as exc:
        raise HTTPException(422, str(exc))
    except local_auth.Conflict as exc:
        raise HTTPException(409, str(exc))
    except local_auth.Unauthorized as exc:
        raise HTTPException(401, str(exc))
    except local_auth.Locked as exc:
        raise HTTPException(429, str(exc))
    except accounts.SessionExpired as exc:
        raise HTTPException(401, str(exc))
    except RuntimeError as exc:                       # DATABASE_URL or AUTH_SECRET is not set
        raise HTTPException(503, str(exc))
    except Exception as exc:
        if type(exc).__name__ in _DB_DOWN:
            raise HTTPException(503, f"The database is not available right now: {type(exc).__name__}")
        raise


@router.post("/register")
def register(body: RegisterIn):
    return _run(local_auth.register, body)


@router.post("/login")
def login(body: LoginIn):
    return _run(local_auth.login, body)


@router.post("/logout-all")
def logout_all(authorization: str | None = Header(default=None)):
    token = accounts.bearer_token(authorization)
    if not token:
        raise HTTPException(401, "Sign in required.")
    try:
        claims = accounts.verify_token(token)
    except ValueError as exc:
        raise HTTPException(401, str(exc))
    return _run(local_auth.sign_out_everywhere, claims)