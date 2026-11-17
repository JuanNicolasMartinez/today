"""Migraciones versionadas y permisos mínimos del rol de la aplicación."""

import shutil

import psycopg
import pytest
from psycopg import errors

from web_app import migrate


def test_migraciones_aplicadas_e_idempotentes(pg, owner):
    assert [m.version for m in pg["applied"]] == [m.version for m in migrate.discover()]
    owner.execute(
        "INSERT INTO today.app_user (username, email, password_hash) VALUES ('fila.previa', 'p@example.test', 'x')"
    )
    try:
        assert migrate.migrate(pg["owner_url"], pg["app_role"]) == []  # nada pendiente
        n = owner.execute("SELECT count(*) FROM today.app_user WHERE username = 'fila.previa'").fetchone()[0]
        assert n == 1  # la fila sobrevive a una nueva ejecución
        status = migrate.status(pg["owner_url"])
        assert all(applied_at for _, applied_at in status)
    finally:
        owner.execute("DELETE FROM today.app_user WHERE username = 'fila.previa'")


def test_migracion_modificada_se_detecta(pg, tmp_path, monkeypatch):
    for f in migrate.MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(f, tmp_path / f.name)
    first = sorted(tmp_path.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- editada\n")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)
    with pytest.raises(migrate.MigrationError, match="cambió"):
        migrate.migrate(pg["owner_url"], pg["app_role"])


def test_rol_de_app_inexistente(pg):
    with pytest.raises(migrate.MigrationError, match="no existe"):
        migrate.migrate(pg["owner_url"], "rol_que_no_existe")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE today.app_user SET username = 'otro.nombre'",
        "INSERT INTO today.app_user (username, email, password_hash, otp_enabled) VALUES ('x.y.z', 'x@e.test', 'h', true)",
        "DELETE FROM today.app_user",
        "DELETE FROM today.user_profile",
        "UPDATE today.user_profile SET credit_score = 950",
        "SELECT * FROM today.schema_migrations",
        "CREATE TABLE today.intrusa (id int)",
        "CREATE TABLE public.intrusa (id int)",
        "DROP TABLE today.user_profile",
        "TRUNCATE today.app_user",
    ],
)
def test_rol_app_tiene_permisos_minimos(pg, statement):
    with psycopg.connect(pg["app_url"]) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(statement)


def test_restricciones_en_la_base(pg):
    """Aunque se salte la validación de la app, PostgreSQL rechaza datos inválidos."""
    with psycopg.connect(pg["app_url"]) as conn:
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                "INSERT INTO today.app_user (username, email, password_hash) VALUES ('Mayus', 'a@b.co', 'h')"
            )


def test_sin_columna_de_rol(owner):
    """La migración 0002 quitó los roles de aplicación (el enunciado no los pide)."""
    cols = {c for (c,) in owner.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'today' AND table_name = 'app_user'"
    ).fetchall()}
    assert "role" not in cols and {"username", "email", "password_hash", "otp_enabled"} <= cols


def test_cli_check_y_unlock(make_user, pg, owner, monkeypatch, capsys):
    from web_app import admin

    assert admin.main(["check"]) == 0
    assert "permisos mínimos: ok" in capsys.readouterr().out
    uid = make_user("cli.prueba").user_id
    owner.execute(
        "UPDATE today.app_user SET failed_attempts = 5, locked_until = now() + interval '15 minutes' WHERE id = %s",
        (uid,),
    )
    monkeypatch.setenv("TODAY_MIGRATOR_DATABASE_URL", pg["owner_url"])
    assert admin.main(["unlock", "CLI.Prueba"]) == 0
    assert admin.main(["unlock", "no.existe"]) == 1
    row = owner.execute("SELECT failed_attempts, locked_until FROM today.app_user WHERE id = %s", (uid,)).fetchone()
    assert row == (0, None)


def test_cli_check_detecta_permisos_excesivos(make_user, pg, owner, capsys):
    from psycopg import sql

    from web_app import admin

    role = sql.Identifier(pg["app_role"])
    owner.execute(sql.SQL("GRANT DELETE ON today.app_user TO {}").format(role))
    try:
        assert admin.main(["check"]) == 1
        assert "REVISAR" in capsys.readouterr().out
    finally:
        owner.execute(sql.SQL("REVOKE DELETE ON today.app_user FROM {}").format(role))
