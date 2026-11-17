"""Migraciones versionadas del esquema ``today``.

Uso (con el rol dueño del esquema, nunca con el rol de la aplicación)::

    uv run --env-file .env today-migrate status
    uv run --env-file .env today-migrate          # aplica las pendientes

Cada archivo ``migrations/NNNN_nombre.sql`` se aplica una sola vez, en su
propia transacción, y queda registrado en ``today.schema_migrations`` con su
suma SHA-256. Si un archivo ya aplicado cambia, el comando se detiene. Un
bloqueo consultivo evita que dos ejecuciones simultáneas se crucen.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from web_app.config import ConfigError, app_role_name, migrator_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_LOCK_KEY = 7_302_021  # bloqueo consultivo exclusivo de este proyecto
_PLACEHOLDER = "{{app_role}}"


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def discover(directory: Path | None = None) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted((directory or MIGRATIONS_DIR).glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"Nombre de migración inválido: {path.name}")
        found.append(Migration(int(match.group(1)), match.group(2), path))
    versions = [m.version for m in found]
    if len(versions) != len(set(versions)):
        raise MigrationError("Hay dos migraciones con el mismo número.")
    return found


def _ensure_meta(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS today")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS today.schema_migrations (
                version    integer     PRIMARY KEY,
                name       text        NOT NULL,
                checksum   text        NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now(),
                applied_by text        NOT NULL DEFAULT current_user
            )
            """
        )


def _applied(conn: psycopg.Connection) -> dict[int, tuple[str, str]]:
    rows = conn.execute(
        "SELECT version, checksum, applied_at::text FROM today.schema_migrations"
    ).fetchall()
    return {v: (c, at) for v, c, at in rows}


def _render(conn: psycopg.Connection, migration: Migration, app_role: str) -> str:
    role_sql = sql.Identifier(app_role).as_string(conn)
    return migration.text.replace(_PLACEHOLDER, role_sql)


def status(conninfo: str) -> list[tuple[Migration, str | None]]:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        _ensure_meta(conn)
        applied = _applied(conn)
    return [(m, applied.get(m.version, (None, None))[1]) for m in discover()]


def migrate(conninfo: str, app_role: str) -> list[Migration]:
    """Aplica las migraciones pendientes y devuelve las que se aplicaron."""
    migrations = discover()
    done: list[Migration] = []
    with psycopg.connect(conninfo, autocommit=True, application_name="today-migrate") as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            exists = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (app_role,)
            ).fetchone()
            if not exists:
                raise MigrationError(
                    f"El rol de aplicación {app_role!r} no existe. Créalo antes "
                    "con db/bootstrap.sql."
                )
            _ensure_meta(conn)
            applied = _applied(conn)
            for m in migrations:
                if m.version in applied and applied[m.version][0] != m.checksum:
                    raise MigrationError(
                        f"La migración {m.path.name} cambió después de aplicarse. "
                        "Crea una migración nueva en vez de editarla."
                    )
            for m in migrations:
                if m.version in applied:
                    continue
                with conn.transaction():
                    conn.execute(_render(conn, m, app_role))
                    conn.execute(
                        "INSERT INTO today.schema_migrations (version, name, checksum)"
                        " VALUES (%s, %s, %s)",
                        (m.version, m.name, m.checksum),
                    )
                done.append(m)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="today-migrate", description=__doc__.split("\n")[0])
    parser.add_argument("command", nargs="?", choices=("up", "status"), default="up")
    args = parser.parse_args(argv)
    try:
        url = migrator_url()
        if args.command == "status":
            for m, applied_at in status(url):
                state = f"aplicada {applied_at}" if applied_at else "pendiente"
                print(f"{m.version:04d}  {m.name:<40} {state}")
            return 0
        done = migrate(url, app_role_name())
    except (ConfigError, MigrationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"error de PostgreSQL: {exc.sqlstate or ''} {type(exc).__name__}", file=sys.stderr)
        return 1
    if done:
        for m in done:
            print(f"aplicada {m.version:04d} {m.name}")
    else:
        print("sin migraciones pendientes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
