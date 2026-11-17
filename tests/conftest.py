"""Fixtures con PostgreSQL real.

Las pruebas de base de datos crean una base y dos roles temporales
(dueño y aplicación), aplican las migraciones con el rol dueño y ejecutan la
aplicación con el rol de permisos mínimos. Al final lo borran todo.

Requiere un superusuario de un PostgreSQL de DESARROLLO:

    TODAY_TEST_ADMIN_URL=postgresql://postgres:...@127.0.0.1:55432/postgres uv run pytest
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import secrets
import uuid
from decimal import Decimal

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ADMIN_URL = os.environ.get("TODAY_TEST_ADMIN_URL", "")

# Tiempo fijo para TOTP en las pruebas: el valor real del reloj no importa.
BASE_NOW = 1_900_000_020.0  # 2030-03-17, a 20 s de iniciar un intervalo


def _url(user: str, password: str, dbname: str) -> str:
    params = conninfo_to_dict(ADMIN_URL)
    params.update(user=user, password=password, dbname=dbname)
    return make_conninfo(**params)


@pytest.fixture(scope="session")
def pg():
    if not ADMIN_URL:
        pytest.skip("Define TODAY_TEST_ADMIN_URL para las pruebas con PostgreSQL.")
    suffix = uuid.uuid4().hex[:8]
    dbname = f"today_test_{suffix}"
    owner, app = f"today_test_owner_{suffix}", f"today_test_app_{suffix}"
    owner_pw, app_pw = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    ident = sql.Identifier

    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        for role, pw in ((owner, owner_pw), (app, app_pw)):
            c.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}"
                ).format(ident(role), sql.Literal(pw))
            )
        c.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(ident(dbname), ident(owner)))
        c.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(ident(dbname)))
        c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(ident(dbname), ident(app)))
    admin_db = conninfo_to_dict(ADMIN_URL) | {"dbname": dbname}
    with psycopg.connect(make_conninfo(**admin_db), autocommit=True) as c:
        c.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")

    from web_app import migrate

    owner_url, app_url = _url(owner, owner_pw, dbname), _url(app, app_pw, dbname)
    applied = migrate.migrate(owner_url, app)
    info = {"owner_url": owner_url, "app_url": app_url, "app_role": app, "applied": applied}
    try:
        yield info
    finally:
        from web_app import db

        db.close_pool()
        with psycopg.connect(ADMIN_URL, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(ident(dbname)))
            for role in (owner, app):
                c.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(ident(role)))


@pytest.fixture(scope="session")
def app_env(pg):
    """Variables de entorno de la app apuntando a la base temporal."""
    from web_app import config, db

    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    old = {k: os.environ.get(k) for k in ("TODAY_DATABASE_URL", "TODAY_OTP_ENCRYPTION_KEY", "TODAY_APP_ROLE", "TODAY_OTP_ISSUER")}
    os.environ.update(
        TODAY_DATABASE_URL=pg["app_url"],
        TODAY_OTP_ENCRYPTION_KEY=key,
        TODAY_APP_ROLE=pg["app_role"],
        TODAY_OTP_ISSUER="today-test",
    )
    config.get_settings.cache_clear()
    db.close_pool()
    yield pg
    db.close_pool()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    config.get_settings.cache_clear()


@pytest.fixture
def owner(pg):
    """Conexión con el rol dueño para preparar estados (no la usa la app)."""
    with psycopg.connect(pg["owner_url"], autocommit=True) as conn:
        yield conn


@pytest.fixture
def clean(app_env, owner):
    owner.execute("TRUNCATE today.user_profile, today.app_user RESTART IDENTITY CASCADE")
    yield app_env


def registration(username: str, *, password: str = "Faro-del-norte 2291", email: str | None = None, **over):
    from web_app.services.accounts import RegistrationData

    data = dict(
        username=username,
        email=email or f"{username.lower()}@example.test",
        password=password,
        password_confirm=password,
        full_name="Ana María Ficticia",
        document_id="1020304050",
        birth_date=dt.date(1991, 3, 14),
        phone="+57 300 123 4567",
        city="Manizales",
        blood_type="O+",
        allergies="",
        chronic_condition="",
        credit_score=710,
        monthly_income=Decimal("4200000"),
        outstanding_debt=Decimal("0"),
    )
    data.update(over)
    return RegistrationData(**data)


@pytest.fixture
def make_user(clean):
    """Registra una cuenta y, por defecto, activa su OTP en BASE_NOW."""
    from web_app.security import otp
    from web_app.services import accounts

    def _make(username: str = "ana.prueba", *, enroll: bool = True, **over):
        ticket = accounts.register(registration(username, **over))
        if enroll:
            code = otp.code_at_step(ticket.secret, otp.current_step(BASE_NOW))
            result = accounts.confirm_enrollment(ticket.user_id, code, now=BASE_NOW)
            assert result.status is accounts.EnrollStatus.ACTIVATED
        return ticket

    return _make
