"""Tareas de administración fuera de la interfaz web.

    uv run --env-file .env today-admin unlock <usuario>             # rol dueño
    uv run --env-file .env today-admin seed-demo --count 12         # rol app
    uv run --env-file .env today-admin check                        # rol app

``unlock`` usa TODAY_MIGRATOR_DATABASE_URL: es una acción de administración
y no pasa por la aplicación. ``seed-demo`` crea cuentas
ficticias por el mismo camino que el formulario (validación + Argon2id) y no
imprime sus contraseñas: sirven como filas para la exportación. ``check`` es la
prueba rápida tras desplegar: valida la configuración y que el rol de la app
conecta y NO puede cambiar el usuario de una cuenta, borrar ni vaciar tablas
ni crear objetos.
"""

from __future__ import annotations

import argparse
import random
import sys

import psycopg

from web_app.config import ConfigError, migrator_url
from web_app.demo_data import fake_registration
from web_app.services import accounts


def _owner_update(sql: str, params: tuple) -> int:
    with psycopg.connect(migrator_url(), application_name="today-admin") as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount


_CHECK_SQL = """
    SELECT current_user AS rol,
           has_table_privilege(current_user, 'today.app_user', 'SELECT') AS lee_cuentas,
           has_column_privilege(current_user, 'today.app_user', 'username', 'UPDATE') AS cambia_usuarios,
           has_table_privilege(current_user, 'today.app_user', 'DELETE') AS borra_cuentas,
           has_table_privilege(current_user, 'today.app_user', 'TRUNCATE') AS vacia_cuentas,
           has_schema_privilege(current_user, 'today', 'CREATE') AS crea_objetos,
           (SELECT count(*) FROM today.app_user) AS cuentas
"""


def check() -> int:
    from web_app import db
    from web_app.config import get_settings

    get_settings()  # falla si falta una variable o la clave no es de 32 bytes
    with db.connection() as conn:
        r = conn.execute(_CHECK_SQL).fetchone()
    ok = r["lee_cuentas"] and not (
        r["cambia_usuarios"] or r["borra_cuentas"] or r["vacia_cuentas"] or r["crea_objetos"]
    )
    print(f"configuración: ok · rol de conexión: {r['rol']}")
    print(f"cuentas: {r['cuentas']}")
    print(
        "permisos mínimos: " + ("ok" if ok else "REVISAR")
        + f" (cambia usuarios={r['cambia_usuarios']}, borra={r['borra_cuentas']}, vacía={r['vacia_cuentas']},"
        f" crea objetos={r['crea_objetos']})"
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="today-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    p_unlock = sub.add_parser("unlock", help="Quita el bloqueo por intentos fallidos")
    p_unlock.add_argument("username")
    p_seed = sub.add_parser("seed-demo", help="Crea cuentas con datos ficticios")
    p_seed.add_argument("--count", type=int, default=12)
    p_seed.add_argument("--seed", type=int, default=None, help="Semilla del generador")
    sub.add_parser("check", help="Prueba posterior al despliegue con el rol de la app")
    args = parser.parse_args(argv)

    try:
        if args.command == "unlock":
            n = _owner_update(
                "UPDATE today.app_user SET failed_attempts = 0, locked_until = NULL WHERE username = %s",
                (accounts.normalize_username(args.username),),
            )
            print("cuenta desbloqueada" if n else "no existe esa cuenta")
            return 0 if n else 1
        if args.command == "check":
            return check()
        if args.command == "seed-demo":
            rng = random.Random(args.seed)
            created = 0
            for i in range(1, args.count + 1):
                try:
                    accounts.register(fake_registration(rng, i))
                    created += 1
                except accounts.RegistrationError:
                    continue
            print(f"cuentas ficticias creadas: {created}")
            return 0
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"error de PostgreSQL: {exc.sqlstate or ''} {type(exc).__name__}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
