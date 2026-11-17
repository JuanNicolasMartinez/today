"""Exportación CSV: contenido exacto, sin secretos y solo para cuentas con sesión válida.

El enunciado no pide roles: cualquier cuenta autenticada (con el segundo factor
activo) puede generarla; una cuenta inexistente o sin OTP, no.
"""

import csv
import io

import pytest

from web_app.services import export


def _rows(data: bytes) -> list[list[str]]:
    assert data.startswith(b"\xef\xbb\xbf")  # BOM UTF-8
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


@pytest.fixture
def requester(make_user):
    return make_user("pide.demo", email="pide@example.test")


def test_csv_contenido(requester, make_user, owner):
    member = make_user(
        "miembro.demo",
        email="miembro@example.test",
        allergies='=HYPERLINK("http://malo.example","clic")',
        chronic_condition="@SUM(1+1)",
        phone="+57 310 555 0101",
    )
    rows = _rows(export.build_csv(requester.user_id))
    header, body = rows[0], rows[1:]
    assert header == [name for name, _ in export.EXPORT_COLUMNS]
    assert len(body) == 2
    by_user = {r[0]: dict(zip(header, r)) for r in body}
    m = by_user["miembro.demo"]
    assert m["correo"] == "miembro@example.test"
    assert "rol" not in header and m["segundo_factor_activo"] == "sí"
    assert m["alergias_demo"] == "'=HYPERLINK(\"http://malo.example\",\"clic\")"
    assert m["condicion_cronica_demo"] == "'@SUM(1+1)"
    assert m["telefono_demo"] == "'+57 310 555 0101"
    assert m["tipo_sangre_demo"] == "O+"
    assert m["puntaje_credito_demo"] == "710"
    assert m["ingreso_mensual_demo"] == "4200000.00"

    text = export.build_csv(requester.user_id).decode("utf-8-sig")
    hashes = [h for (h,) in owner.execute("SELECT password_hash FROM today.app_user").fetchall()]
    for forbidden in [*hashes, "$argon2", requester.secret, member.secret, "password", "otp_", "secret",
                      "failed_attempts", "locked_until"]:
        assert forbidden not in text


def test_cualquier_cuenta_con_otp_puede_descargar(make_user):
    for name in ("uno.demo", "dos.demo"):
        assert _rows(export.build_csv(make_user(name).user_id))[0][0] == "usuario"


@pytest.mark.parametrize("who", ["inexistente", "sin_otp"])
def test_csv_denegado(make_user, who):
    uid = 999_999 if who == "inexistente" else make_user("pendiente.demo", enroll=False).user_id
    with pytest.raises(export.ExportPermissionError):
        export.build_csv(uid)


def test_permiso_se_revisa_al_ejecutar(requester, owner):
    """Si la cuenta deja de existir después de pintar el botón, la descarga se niega."""
    assert export.build_csv(requester.user_id)
    owner.execute("DELETE FROM today.user_profile WHERE user_id = %s", (requester.user_id,))
    owner.execute("DELETE FROM today.app_user WHERE id = %s", (requester.user_id,))
    with pytest.raises(export.ExportPermissionError):
        export.build_csv(requester.user_id)


def test_csv_no_consulta_datos_si_no_hay_permiso(make_user, monkeypatch):
    """El permiso se verifica antes de consultar los datos de demostración."""
    from contextlib import contextmanager

    from web_app import db

    uid = make_user("pendiente.demo", enroll=False).user_id
    seen: list[str] = []
    real = db.connection

    class Spy:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, query, *args, **kwargs):
            seen.append(str(query))
            return self._conn.execute(query, *args, **kwargs)

        def transaction(self):
            return self._conn.transaction()

    @contextmanager
    def spy():
        with real() as conn:
            yield Spy(conn)

    monkeypatch.setattr(db, "connection", spy)
    with pytest.raises(export.ExportPermissionError):
        export.build_csv(uid)
    assert len(seen) == 1 and "otp_enabled" in seen[0] and "user_profile" not in seen[0]


def test_nombre_de_archivo():
    name = export.export_filename()
    assert name.startswith("today_demo_") and name.endswith(".csv")
