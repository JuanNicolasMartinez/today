"""Pool de conexiones PostgreSQL para el rol de la aplicación."""

from __future__ import annotations

import atexit
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from web_app.config import get_settings

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def _configure(conn: psycopg.Connection) -> None:
    # Tiempo máximo por sentencia: evita que una consulta bloquee la sesión.
    conn.execute("SET statement_timeout = '5s'")
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=get_settings().database_url,
                    min_size=1,
                    max_size=8,
                    kwargs={"row_factory": dict_row, "application_name": "today-web"},
                    configure=_configure,
                    open=True,
                    name="today",
                )
                atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Conexión del pool. ``with conn.transaction()`` delimita cada operación."""
    with get_pool().connection() as conn:
        yield conn
