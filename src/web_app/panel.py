"""Vistas del panel de la cuenta (una página por sección, navegadas desde el riel).

Cada vista vuelve a leer la sesión y la cuenta desde PostgreSQL. La descarga
CSV está disponible para cualquier cuenta con sesión; al generar el archivo se
vuelve a comprobar en la base que la cuenta existe y tiene el segundo factor
activo.
"""

from __future__ import annotations

import streamlit as st

from web_app import session
from web_app.services import accounts, export
from web_app.ui import theme


def _money(value) -> str:
    return "—" if value is None else f"$ {value:,.0f}".replace(",", ".")


def _mask(value: str | None) -> str:
    if not value:
        return "—"
    return "•" * max(len(value) - 4, 0) + value[-4:]


def _or_none(value) -> str:
    return value if value else "Ninguna"


def _load() -> tuple[accounts.User, dict]:
    user = session.current_user()
    if user is None:  # main.py ya lo impide; se comprueba otra vez por si acaso
        st.stop()
    return user, accounts.get_account(user.id) or {}


# --------------------------------------------------------------------------


def export_block(user: accounts.User) -> None:
    """Descarga de todos los usuarios en CSV."""
    theme.heading("Descargar usuarios", "Todas las cuentas con sus datos de demostración, en CSV.", level=2)
    with st.container(key="export", horizontal=True, vertical_alignment="center", gap="medium"):
        theme.export_text(
            "table_view",
            f"usuarios.csv · {len(export.EXPORT_COLUMNS)} columnas",
            "",
        )
        uid = user.id  # se captura aquí: el callable corre en otro hilo, sin session_state

        def _generate() -> bytes:
            # Se vuelve a comprobar el rol en la base al hacer clic, antes de consultar.
            return export.build_csv(uid)

        st.download_button(
            "Descargar CSV",
            data=_generate,
            file_name=export.export_filename(),
            mime="text/csv",
            on_click="ignore",
            key="export_csv",
            icon=":material/download:",
            type="primary",
        )


def resumen() -> None:
    user, a = _load()
    name = a.get("full_name") or user.username
    with st.container(key="view-resumen"):
        theme.heading(f"Hola, {name.split()[0]}", "")
        theme.mosaic(
            [
                theme.Tile(name, f"@{user.username}", tone="pink", tall=True, person=name),
                theme.Tile("Ciudad", a.get("city") or "—", glyph="location_on", tone="peach"),
                theme.Tile("Sangre", a.get("blood_type") or "—", glyph="bloodtype", tone="lilac"),
                theme.Tile("Puntaje", str(a.get("credit_score") or "—"), glyph="speed", tone="mint"),
                theme.Tile("Correo", a.get("email") or "—", glyph="mail", tone="white", wide=True),
                theme.Tile("2FA", "Activo" if a.get("otp_enabled") else "Inactivo", glyph="verified_user",
                           tone="fog"),
            ],
            cols=4,
        )
        export_block(user)


def personal() -> None:
    user, a = _load()
    with st.container(key="view-personal"):
        theme.heading("Datos personales", "")
        theme.mosaic(
            [
                theme.Tile("Nombre completo", a.get("full_name") or "—", glyph="badge", tone="peach", wide=True),
                theme.Tile("Documento", _mask(a.get("document_id")), glyph="id_card", tone="white", wide=True),
                theme.Tile("Nacimiento", theme.fmt_day(a.get("birth_date")), glyph="cake", tone="pink", wide=True),
                theme.Tile("Teléfono", a.get("phone") or "—", glyph="call", tone="mint", wide=True),
                theme.Tile("Ciudad", a.get("city") or "—", glyph="location_on", tone="lilac", wide=True),
                theme.Tile("Usuario", f"@{user.username}", glyph="alternate_email", tone="fog", wide=True),
            ],
            cols=4,
        )


def salud() -> None:
    _, a = _load()
    with st.container(key="view-salud"):
        theme.heading("Salud", "")
        theme.mosaic(
            [
                theme.Tile("Tipo de sangre", a.get("blood_type") or "—", glyph="bloodtype", tone="pink", tall=True),
                theme.Tile("Alergias", _or_none(a.get("allergies")), glyph="allergy", tone="peach", wide=True),
                theme.Tile("Condición crónica", _or_none(a.get("chronic_condition")), glyph="ecg_heart",
                           tone="lilac", wide=True),
            ],
            cols=3,
        )


def credito() -> None:
    _, a = _load()
    lo, hi = accounts.CREDIT_SCORE_RANGE
    with st.container(key="view-credito"):
        theme.heading("Crédito", "")
        theme.score_bar(a.get("credit_score"), lo, hi)
        theme.mosaic(
            [
                theme.Tile("Ingreso mensual", _money(a.get("monthly_income")), glyph="payments", tone="mint",
                           wide=True),
                theme.Tile("Deuda vigente", _money(a.get("outstanding_debt")), glyph="account_balance",
                           tone="peach", wide=True),
            ],
            cols=4,
        )


def seguridad() -> None:
    user, a = _load()
    with st.container(key="view-seguridad"):
        theme.heading("Seguridad", "Cómo está protegida tu cuenta.")
        theme.mosaic(
            [
                theme.Tile("Autenticador", "Activo" if a.get("otp_enabled") else "Inactivo", glyph="verified_user",
                           tone="mint", wide=True),
                theme.Tile("Contraseña", "Argon2id con sal", glyph="password", tone="lilac", wide=True),
                theme.Tile("Bloqueo", "5 intentos · 15 min", glyph="lock_clock", tone="peach", wide=True),
                theme.Tile("Sesión", "Se cierra tras 30 min sin uso", glyph="timer", tone="pink", wide=True),
            ],
            cols=4,
        )
        theme.boxes([
            ("Último acceso", theme.fmt_dt(a.get("last_login_at"))),
            ("Cuenta creada", theme.fmt_dt(a.get("created_at"))),
        ])
