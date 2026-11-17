"""Exportación CSV de los datos de demostración.

* La puede generar cualquier cuenta con sesión autenticada (el enunciado no
  pide roles). Antes de consultar los datos se comprueba en la base que la
  cuenta que la pide existe y tiene el segundo factor activo.
* Las columnas son una lista explícita. Nunca incluye hashes, semillas OTP,
  contadores de intentos, credenciales ni tokens.
* Cada celda de texto se neutraliza para que una hoja de cálculo no la
  interprete como fórmula (inyección CSV).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from decimal import Decimal

from web_app import db

log = logging.getLogger("today.export")

# (columna en el CSV, expresión SQL). Lista cerrada: añadir una columna exige
# editar esta tupla y su prueba.
EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("usuario", "u.username"),
    ("correo", "u.email"),
    ("segundo_factor_activo", "u.otp_enabled"),
    ("creado_en", "u.created_at"),
    ("nombre_completo_demo", "p.full_name"),
    ("documento_demo", "p.document_id"),
    ("fecha_nacimiento_demo", "p.birth_date"),
    ("telefono_demo", "p.phone"),
    ("ciudad_demo", "p.city"),
    ("tipo_sangre_demo", "p.blood_type"),
    ("alergias_demo", "p.allergies"),
    ("condicion_cronica_demo", "p.chronic_condition"),
    ("puntaje_credito_demo", "p.credit_score"),
    ("ingreso_mensual_demo", "p.monthly_income"),
    ("deuda_vigente_demo", "p.outstanding_debt"),
)

_EXPORT_SQL = (
    "SELECT "
    + ", ".join(expr for _, expr in EXPORT_COLUMNS)
    + " FROM today.app_user u JOIN today.user_profile p ON p.user_id = u.id"
    " ORDER BY u.id"
)

# Prefijos que Excel, LibreOffice o Google Sheets pueden evaluar como fórmula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")


class ExportPermissionError(PermissionError):
    pass


def neutralize(value: str) -> str:
    """Antepone un apóstrofo si la celda empieza (tras espacios) como fórmula."""
    stripped = value.lstrip(" ")
    if value and (value.startswith(_FORMULA_PREFIXES) or stripped.startswith(_FORMULA_PREFIXES)):
        return "'" + value
    return value


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, dt.datetime):
        text = value.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    elif isinstance(value, dt.date):
        text = value.isoformat()
    elif isinstance(value, Decimal):
        text = f"{value:.2f}"
    else:
        text = str(value)
    return neutralize(text)


def build_csv(requesting_user_id: int) -> bytes:
    """Verifica el permiso y, solo entonces, consulta y construye el CSV."""
    with db.connection() as conn, conn.transaction():
        requester = conn.execute(
            "SELECT otp_enabled FROM today.app_user WHERE id = %s",
            (requesting_user_id,),
        ).fetchone()
        if not requester or not requester["otp_enabled"]:
            log.warning("event=export_denied user_id=%s", requesting_user_id)
            raise ExportPermissionError("No autorizado.")
        rows = conn.execute(_EXPORT_SQL).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([name for name, _ in EXPORT_COLUMNS])
    for row in rows:
        writer.writerow([_cell(v) for v in row.values()])
    log.info("event=export_ok user_id=%s rows=%s", requesting_user_id, len(rows))
    # BOM UTF-8 para que Excel muestre bien las tildes.
    return buf.getvalue().encode("utf-8-sig")


def export_filename(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return f"today_demo_{now:%Y%m%d_%H%M}.csv"
