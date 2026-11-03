"""Connection to the Neon database. Only accounts use it; guests never touch it.
Set DATABASE_URL to your Neon *pooled* connection string (the one with -pooler in the host name).
Never write the connection string in code: it holds the database password. Keep it in .env (which git ignores)
or in your host's environment settings."""
from __future__ import annotations

import os
from contextlib import contextmanager
from importlib import import_module

_pool = None


def configured() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def pool():
    """One shared pool of connections, created on first use."""
    global _pool
    if _pool is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set.")
        dict_row = import_module("psycopg.rows").dict_row  # lazy: app runs without the database library
        ConnectionPool = import_module("psycopg_pool").ConnectionPool
        _pool = ConnectionPool(
            url, min_size=0, max_size=5, timeout=15, max_idle=300, open=False,
            check=ConnectionPool.check_connection,    # drops dead connections (Neon sleeps when idle)
            kwargs={"row_factory": dict_row, "prepare_threshold": None},  # None = compatible with Neon's pooled connections
        )
        _pool.open()
    return _pool


@contextmanager
def connection():
    """`with db.connection() as conn:` commits when the block ends normally and rolls back if it raises."""
    with pool().connection() as conn:
        yield conn