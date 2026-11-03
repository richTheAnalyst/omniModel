"""Database fixtures for tests/test_tracking.py.

Those tests need a real Postgres. Point them at a throwaway database whose name contains "test":

    TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/omni_test" pytest tests/test_tracking.py

For Neon, use a separate branch and its DIRECT connection string (the host without "-pooler": the pooler refuses the
search_path option used below). Every run creates its own schema, applies omnimodel/schema.sql inside it and drops it
at the end, so nothing else in that database is touched. Put TEST_DATABASE_URL in your shell or in .env (only that one line is read from .env). Without it the database tests are skipped.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from urllib.parse import quote, urlparse

import pytest

SCHEMA_SQL = pathlib.Path(__file__).resolve().parent.parent / "omnimodel" / "schema.sql"
ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env"


def _test_url_from_dotenv() -> str | None:
    """pytest does not read .env by itself. Read only the TEST_DATABASE_URL line from it, and nothing else,
    so the real DATABASE_URL in that file is never loaded into the tests."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    if not ENV_FILE.exists():
        return None
    value = (dotenv_values(ENV_FILE).get("TEST_DATABASE_URL") or "").strip()
    return value or None


@pytest.fixture(scope="session")
def database():
    url = os.getenv("TEST_DATABASE_URL") or _test_url_from_dotenv()
    if not url:
        pytest.skip("Set TEST_DATABASE_URL (in the environment or in .env) to a throwaway Postgres database to run the tracking tests.")
    name = urlparse(url).path.lstrip("/")
    if "test" not in name.lower():
        pytest.fail(f"Refusing to run: the database name '{name}' does not contain 'test'. Use a throwaway database.")
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from omnimodel import db

    schema = "t_" + uuid.uuid4().hex[:12]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'create schema "{schema}"')
        conn.execute(f'set search_path to "{schema}"')
        conn.execute(SCHEMA_SQL.read_text())
    scoped = url + ("&" if "?" in url else "?") + "options=" + quote(f"-c search_path={schema}")

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scoped
    db._pool = None
    yield schema
    if db._pool is not None:
        db._pool.close()
        db._pool = None
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'drop schema "{schema}" cascade')


@pytest.fixture()
def member(database):
    """make(name) -> a signed-in user in a brand-new business of their own (a tracking.Ctx)."""
    from omnimodel import tracking

    def make(name: str = "user") -> tracking.Ctx:
        sub = f"{name}-{uuid.uuid4().hex[:8]}"
        return tracking.resolve_member({"sub": sub, "email": f"{sub}@example.com", "name": name})

    return make