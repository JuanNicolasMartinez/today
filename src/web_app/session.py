"""Estado de sesión autenticada en Streamlit.

``st.session_state`` vive en el servidor y está ligado a la conexión del
navegador. Solo guarda el id de la cuenta y marcas de tiempo. El rol y el
estado del segundo factor se vuelven a leer de PostgreSQL en cada ejecución
y antes de cada acción protegida.
"""

from __future__ import annotations

import time

import streamlit as st

from web_app.services import accounts

AUTH_KEY = "_auth"
ENROLL_KEY = "_enroll_user_id"
IDLE_TIMEOUT_S = 30 * 60
ABSOLUTE_TIMEOUT_S = 8 * 60 * 60


def sign_in(user: accounts.User) -> None:
    """Crea la sesión autenticada desde un estado limpio."""
    st.session_state.clear()
    now = time.time()
    st.session_state[AUTH_KEY] = {"user_id": user.id, "issued": now, "seen": now}


def sign_out() -> None:
    st.session_state.clear()


def current_user() -> accounts.User | None:
    """Usuario autenticado y vigente, leído de la base; ``None`` si no hay."""
    auth = st.session_state.get(AUTH_KEY)
    if not isinstance(auth, dict):
        return None
    now = time.time()
    if now - auth.get("seen", 0) > IDLE_TIMEOUT_S or now - auth.get("issued", 0) > ABSOLUTE_TIMEOUT_S:
        sign_out()
        return None
    user = accounts.get_user(int(auth["user_id"]))
    if user is None or not user.otp_enabled:
        sign_out()
        return None
    auth["seen"] = now
    return user


def begin_enrollment(user_id: int) -> None:
    st.session_state.pop(AUTH_KEY, None)
    st.session_state[ENROLL_KEY] = user_id


def enrollment_user_id() -> int | None:
    value = st.session_state.get(ENROLL_KEY)
    return value if isinstance(value, int) else None


def end_enrollment() -> None:
    st.session_state.pop(ENROLL_KEY, None)
