"""Acceso: inicio de sesión en dos pasos, registro en tres y configuración del autenticador.

Inicio de sesión: el paso 1 pide usuario y contraseña; el paso 2, el código de
la app autenticadora. Los tres datos se verifican juntos al final
(``authenticate``), así que un error nunca revela cuál falló ni se puede usar
el paso 1 para probar contraseñas.

Registro: 1) cuenta, 2) datos de demostración, 3) autenticador. El paso 1 se
valida con las mismas reglas del servidor, sin tocar la base; la cuenta se
crea al terminar el paso 2 y los duplicados los detecta PostgreSQL.

Entre pasos, la contraseña queda solo en la memoria de la sesión del servidor
(5 minutos en el login, 15 en el registro) y se borra con cualquier resultado.
Las acciones se procesan en callbacks: así se vacían los campos de contraseña y
código antes de volver a pintar la página.
"""

import base64
import datetime as dt
import logging
import random
import time

import streamlit as st

from web_app import session
from web_app.demo_data import fake_registration
from web_app.security import otp
from web_app.services import accounts
from web_app.team import TEAM
from web_app.ui import theme

log = logging.getLogger("today.ui")

VIEW = "_auth_view"  # login | code | register | demo
PENDING = "_login_pending"
PENDING_TTL_S = 5 * 60
REG_PENDING = "_reg_account"
REG_TTL_S = 15 * 60
REG_DEMO = "_reg_demo"
FLASH = "_flash"
TOAST = "_toast"
TOAST_SEQ = "_toast_seq"
TOAST_TONES = ("error", "warn")
REG_ERRORS = "_reg_errors"
GENERIC_LOGIN_ERROR = "No pudimos verificar tus datos. Revisa usuario, contraseña y código."
SERVICE_ERROR = "El servicio no está disponible en este momento. Intenta de nuevo más tarde."
RESTART_HINT = "Inicia sesión y elige «Configúralo» para obtener un QR nuevo."
RETYPE_PASSWORD = "Por seguridad, vuelve a escribir la contraseña."

# La fecha de nacimiento se pide en tres listas (día, mes, año): el calendario de
# st.date_input solo ofrece 20 años a la vez en su lista de años.
BIRTH_PARTS = ("birth_day", "birth_month", "birth_year")
MONTHS = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
DEMO_FIELDS = (
    "full_name", "document_id", *BIRTH_PARTS, "phone", "city", "blood_type",
    "allergies", "chronic_condition", "credit_score", "monthly_income", "outstanding_debt",
)

LOGIN_STEPS = (
    theme.Step("Usuario y contraseña", "Primero, quién eres.", "person", "pink"),
    theme.Step("Código de la app", "Los seis dígitos de tu autenticador.", "smartphone", "lilac"),
    theme.Step("Tu panel", "Tus datos y la descarga de usuarios.", "space_dashboard", "mint"),
)
REGISTER_STEPS = (
    theme.Step("Cuenta", "Usuario, correo y contraseña.", "person_add", "pink"),
    theme.Step("Datos de demostración", "Personales, salud y crédito, todos ficticios.", "badge", "peach"),
    theme.Step("Autenticador", "Escanea el QR y confirma un código.", "qr_code_2", "lilac"),
)


def _flash(message: str, tone: str) -> None:
    st.session_state[FLASH] = (message, tone)
    if tone in TOAST_TONES:
        st.session_state[TOAST] = (message, tone)


def _toast_errors(errors: dict[str, str]) -> None:
    """Toast para errores por campo: el mensaje si es uno solo, o cuántos campos revisar."""
    messages = [m for m in errors.values() if m != RETYPE_PASSWORD] or list(errors.values())
    if not messages:
        return
    text = messages[0] if len(messages) == 1 else f"Revisa los {len(messages)} campos marcados."
    st.session_state[TOAST] = (text, "error")


def _show_toast() -> None:
    """Muestra el toast pendiente; desaparece en la siguiente ejecución de la página."""
    item = st.session_state.pop(TOAST, None)
    if item:
        n = st.session_state[TOAST_SEQ] = st.session_state.get(TOAST_SEQ, 0) + 1
        theme.toast(*item, nonce=n)


def _show_flash() -> None:
    item = st.session_state.pop(FLASH, None)
    if item:
        theme.notice(*item)


def _fresh(key: str, ttl_s: int) -> dict | None:
    item = st.session_state.get(key)
    if not isinstance(item, dict) or time.time() - item.get("at", 0) > ttl_s:
        st.session_state.pop(key, None)
        return None
    return item


def _stash_demo() -> None:
    """Guarda los datos de demostración al volver al paso 1 (sus widgets desaparecen)."""
    st.session_state[REG_DEMO] = {f: st.session_state.get(f"reg_{f}") for f in DEMO_FIELDS}


def _restore_demo() -> None:
    for f, value in (st.session_state.get(REG_DEMO) or {}).items():
        if value is not None:
            st.session_state[f"reg_{f}"] = value


def _birth_years() -> list[int]:
    """Del año en que hoy se cumplen 18 hacia atrás, hasta 1900 (el servidor revisa el día exacto)."""
    return list(range(dt.date.today().year - 18, 1899, -1))


def _birth_date(v: dict) -> dt.date | None:
    """Une día, mes y año; si falta uno o la fecha no existe (31 de febrero), el servidor la rechaza."""
    try:
        return dt.date(int(v["birth_year"]), int(v["birth_month"]), int(v["birth_day"]))
    except (TypeError, ValueError):
        return None


def _back_to_account(pending: dict, errors: dict[str, str]) -> None:
    s = st.session_state
    s.pop(REG_PENDING, None)
    s["reg_username"] = pending["username"]
    s["reg_email"] = pending["email"]
    s[REG_ERRORS] = errors
    s[VIEW] = "register"


def _clear_registration() -> None:
    s = st.session_state
    for f in (*accounts.ACCOUNT_FIELDS, *DEMO_FIELDS):
        s.pop(f"reg_{f}", None)
    for key in (REG_ERRORS, REG_PENDING, REG_DEMO):
        s.pop(key, None)


# --------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------


def _go(view: str) -> None:
    s = st.session_state
    s.pop(PENDING, None)
    s["login_pass"] = ""
    if view not in ("register", "demo"):
        _clear_registration()
    s[VIEW] = view


def _on_credentials() -> None:
    s = st.session_state
    username, password = s.get("login_user", ""), s.get("login_pass", "")
    s["login_pass"] = ""
    if not username.strip() or not password:
        _flash("Escribe tu usuario y tu contraseña.", "error")
        return
    s[PENDING] = {"username": username.strip(), "password": password, "at": time.time()}
    s[VIEW] = "code"


def _on_code() -> None:
    s = st.session_state
    code = s.get("otp_login", "")
    s["otp_login"] = ""
    pending = _fresh(PENDING, PENDING_TTL_S)
    if pending is None:
        s[VIEW] = "login"
        _flash("La verificación expiró. Vuelve a escribir tus datos.", "warn")
        return
    if not code.strip():
        _flash("Escribe el código de seis dígitos.", "error")
        return
    s.pop(PENDING, None)  # un intento por paso 1, sea cual sea el resultado
    try:
        user = accounts.authenticate(pending["username"], pending["password"], code)
    except Exception as exc:  # base de datos caída, configuración, etc.
        log.error("event=login_unavailable error=%s", type(exc).__name__)
        s[VIEW] = "login"
        _flash(SERVICE_ERROR, "error")
        return
    if user is None:
        s[VIEW] = "login"
        _flash(GENERIC_LOGIN_ERROR, "error")
        return
    session.sign_in(user)  # limpia todo el estado; main.py muestra el panel


def _on_start_enroll() -> None:
    s = st.session_state
    pending = _fresh(PENDING, PENDING_TTL_S)
    s.pop(PENDING, None)
    s["otp_login"] = ""
    s[VIEW] = "login"
    if pending is None:
        _flash("La verificación expiró. Vuelve a escribir tus datos.", "warn")
        return
    try:
        ticket = accounts.start_enrollment(pending["username"], pending["password"])
    except Exception as exc:
        log.error("event=enroll_unavailable error=%s", type(exc).__name__)
        _flash(SERVICE_ERROR, "error")
        return
    if ticket is None:
        _flash("No fue posible configurar el autenticador con esos datos.", "error")
        return
    session.begin_enrollment(ticket.user_id)


def _on_reg_next() -> None:
    """Paso 1 → 2: valida la cuenta con las reglas del servidor, sin tocar la base."""
    s = st.session_state
    username, email = s.get("reg_username", ""), s.get("reg_email", "")
    password, confirm = s.get("reg_password", ""), s.get("reg_password_confirm", "")
    s["reg_password"] = ""
    s["reg_password_confirm"] = ""
    errors = accounts.validate_account(username, email, password, confirm)
    if errors:
        if "password" not in errors and "password_confirm" not in errors:
            errors["password"] = RETYPE_PASSWORD
        s[REG_ERRORS] = errors
        _toast_errors(errors)
        return
    s.pop(REG_ERRORS, None)
    s[REG_PENDING] = {"username": username, "email": email, "password": password, "at": time.time()}
    _restore_demo()
    s[VIEW] = "demo"


def _on_reg_back() -> None:
    pending = st.session_state.get(REG_PENDING) or {"username": "", "email": ""}
    _stash_demo()
    _back_to_account(pending, {})
    _flash("Vuelve a escribir la contraseña para continuar.", "neutral")


def _on_fill_demo() -> None:
    fake = fake_registration(random.Random(), random.randint(1, 99))
    s = st.session_state
    for f in ("full_name", "document_id", "phone", "city", "blood_type",
              "allergies", "chronic_condition", "credit_score"):
        s[f"reg_{f}"] = getattr(fake, f)
    s["reg_birth_day"] = fake.birth_date.day
    s["reg_birth_month"] = fake.birth_date.month
    s["reg_birth_year"] = fake.birth_date.year
    s["reg_monthly_income"] = float(fake.monthly_income)
    s["reg_outstanding_debt"] = float(fake.outstanding_debt)


def _on_register() -> None:
    """Paso 2 → 3: crea la cuenta (PostgreSQL decide si el usuario o el correo ya existen)."""
    s = st.session_state
    pending = _fresh(REG_PENDING, REG_TTL_S)
    if pending is None:
        _stash_demo()
        s[VIEW] = "register"
        _flash("Pasó demasiado tiempo. Vuelve a escribir los datos de la cuenta.", "warn")
        return
    v = {f: s.get(f"reg_{f}") for f in DEMO_FIELDS}
    data = accounts.RegistrationData(
        username=pending["username"], email=pending["email"],
        password=pending["password"], password_confirm=pending["password"],
        **{f: v[f] or "" for f in ("full_name", "document_id", "phone", "city", "blood_type",
                                   "allergies", "chronic_condition")},
        birth_date=_birth_date(v),
        credit_score=int(v["credit_score"]) if v["credit_score"] is not None else None,
        monthly_income=v["monthly_income"],
        outstanding_debt=v["outstanding_debt"],
    )
    try:
        ticket = accounts.register(data)
    except accounts.RegistrationError as exc:
        account_errors = {k: m for k, m in exc.errors.items() if k in accounts.ACCOUNT_FIELDS}
        if account_errors:  # p. ej., el usuario o el correo ya existen
            _stash_demo()
            _back_to_account(pending, {"password": RETYPE_PASSWORD, **account_errors})
        else:
            s[REG_ERRORS] = exc.errors
        _toast_errors(exc.errors)
        return
    except Exception as exc:
        log.error("event=register_unavailable error=%s", type(exc).__name__)
        _flash(SERVICE_ERROR, "error")
        return
    _clear_registration()
    session.begin_enrollment(ticket.user_id)


def _on_confirm_enroll() -> None:
    s = st.session_state
    code = s.get("otp_enroll", "")
    s["otp_enroll"] = ""
    uid = session.enrollment_user_id()
    if uid is None:
        return
    try:
        result = accounts.confirm_enrollment(uid, code)
    except Exception as exc:
        log.error("event=enroll_confirm_unavailable error=%s", type(exc).__name__)
        _flash(SERVICE_ERROR, "error")
        return
    match result.status:
        case accounts.EnrollStatus.ACTIVATED:
            session.end_enrollment()
            s[VIEW] = "login"
            _flash("Autenticador listo. Inicia sesión con tu usuario, tu contraseña y el próximo código.", "ok")
        case accounts.EnrollStatus.INVALID:
            plural = "intento" if result.attempts_left == 1 else "intentos"
            _flash(f"Ese código no coincide. Te quedan {result.attempts_left} {plural}.", "error")
        case accounts.EnrollStatus.EXHAUSTED:
            session.end_enrollment()
            s[VIEW] = "login"
            _flash(f"Se agotaron los intentos. {RESTART_HINT}", "warn")
        case _:
            session.end_enrollment()
            s[VIEW] = "login"
            _flash(f"El QR venció. {RESTART_HINT}", "warn")


def _on_cancel_enroll() -> None:
    uid = session.enrollment_user_id()
    if uid is not None:
        try:
            accounts.cancel_enrollment(uid)
        except Exception as exc:
            log.error("event=enroll_cancel_unavailable error=%s", type(exc).__name__)
    session.end_enrollment()
    st.session_state[VIEW] = "login"


# --------------------------------------------------------------------------
# Vistas
# --------------------------------------------------------------------------


def aside(title: str, sub: str, steps: tuple[theme.Step, ...], current: int) -> None:
    """Columna derecha: el recorrido con el paso actual y el equipo."""
    with st.container(key="aside"):
        theme.heading(title, sub, level=2)
        theme.journey(steps, current)
        theme.team(TEAM)


def login_aside(current: int) -> None:
    aside("Cómo entrar:", "", LOGIN_STEPS, current)


def register_aside(current: int) -> None:
    aside("Cómo crear una cuenta", "", REGISTER_STEPS, current)


def view_login() -> None:
    left, right = st.columns([1, 1.12], gap="large")
    with left, st.container(key="auth-main"):
        theme.logo()
        theme.heading("Inicia sesión", "")
        _show_flash()
        with st.form("login", border=False, enter_to_submit=True):
            st.text_input("Usuario", key="login_user", max_chars=32, autocomplete="username",
                          icon=":material/person:", placeholder="tu.usuario")
            st.text_input("Contraseña", key="login_pass", type="password", max_chars=128,
                          autocomplete="current-password", icon=":material/lock:")
            st.form_submit_button("Continuar", type="primary", on_click=_on_credentials, width="stretch")
        with st.container(key="switch", horizontal=True, vertical_alignment="center", gap="small"):
            theme.text_row("")
            st.button("Crear cuenta", key="to_register", type="tertiary", on_click=_go, args=("register",))
    with right:
        login_aside(0)


def view_code(pending: dict) -> None:
    left, right = st.columns([1, 1.12], gap="large")
    with left, st.container(key="auth-main"):
        theme.logo()
        st.button("Cambiar usuario", key="back", type="tertiary", icon=":material/arrow_back:",
                  on_click=_go, args=("login",))
        theme.heading("Verificación en dos pasos",
                      f"Escribe el código de seis dígitos que muestra tu app autenticadora para @{pending['username']}.")
        _show_flash()
        with st.form("otp", border=False, enter_to_submit=True):
            st.text_input("Código", key="otp_login", max_chars=6, placeholder="000000",
                          autocomplete="one-time-code", icon=":material/pin:")
            st.form_submit_button("Verificar e ingresar", type="primary", on_click=_on_code, width="stretch")
        with st.container(key="switch", horizontal=True, vertical_alignment="center", gap="small"):
            theme.text_row("¿Aún no configuras el autenticador?")
            st.button("Configúralo", key="start_enroll", type="tertiary", on_click=_on_start_enroll)
    with right:
        login_aside(1)


def _err(errors: dict[str, str], field: str) -> None:
    theme.field_error(errors.get(field))


def view_register() -> None:
    errors: dict[str, str] = st.session_state.get(REG_ERRORS, {})
    left, right = st.columns([1, 1.12], gap="large")
    with left, st.container(key="auth-main"):
        theme.logo()
        theme.heading("Crea tu cuenta", "Paso 1 de 3 · Los datos con los que vas a entrar.")
        if errors.get("form"):
            theme.notice(errors["form"], "error")
        _show_flash()
        with st.form("register", border=False, enter_to_submit=True):
            st.text_input("Usuario", key="reg_username", max_chars=32, autocomplete="username",
                          icon=":material/person:", placeholder="ana.rojas")
            _err(errors, "username")
            st.text_input("Correo", key="reg_email", max_chars=254, autocomplete="email",
                          icon=":material/mail:", placeholder="ana@example.test")
            _err(errors, "email")
            st.text_input("Contraseña", key="reg_password", type="password", max_chars=128,
                          autocomplete="new-password", icon=":material/lock:")
            _err(errors, "password")
            st.text_input("Repite la contraseña", key="reg_password_confirm", type="password",
                          max_chars=128, autocomplete="new-password", icon=":material/lock:")
            _err(errors, "password_confirm")
            theme.hint("Mínimo 12 caracteres, con letras y al menos un número o símbolo. "
                       "Sin tu usuario ni contraseñas comunes.")
            st.form_submit_button("Siguiente", type="primary", on_click=_on_reg_next, width="stretch",
                                  icon=":material/arrow_forward:", icon_position="right")
        with st.container(key="switch", horizontal=True, vertical_alignment="center", gap="small"):
            theme.text_row("")
            st.button("Inicia sesión", key="to_login", type="tertiary", on_click=_go, args=("login",))
    with right:
        register_aside(0)


def view_demo(pending: dict) -> None:
    errors: dict[str, str] = st.session_state.get(REG_ERRORS, {})
    left, right = st.columns([1.2, 1], gap="large")
    with left, st.container(key="auth-main"):
        theme.logo()
        theme.heading("Datos de demostración",
                      f"Paso 2 de 3 · Perfil académico de @{pending['username']}.")
        theme.notice("Son datos de práctica para la entrega: escribe solo datos inventados "
                     "o usa «Llenar con datos ficticios».", "demo")
        if errors.get("form"):
            theme.notice(errors["form"], "error")
        _show_flash()
        with st.form("demo", border=False, enter_to_submit=False):
            st.form_submit_button("Llenar con datos ficticios", type="secondary",
                                  icon=":material/shuffle:", on_click=_on_fill_demo)

            with st.container(key="grp-peach"):
                theme.group_title("badge", "Personales", "demo")
                c1, c2 = st.columns([1.6, 1])
                with c1:
                    st.text_input("Nombre completo", key="reg_full_name", max_chars=120, autocomplete="off")
                    _err(errors, "full_name")
                with c2:
                    st.text_input("Ciudad", key="reg_city", max_chars=80, autocomplete="off")
                    _err(errors, "city")
                c1, c2 = st.columns(2)
                with c1:
                    st.text_input("Documento", key="reg_document_id", max_chars=20, autocomplete="off")
                    _err(errors, "document_id")
                with c2:
                    st.text_input("Teléfono", key="reg_phone", max_chars=20, autocomplete="off",
                                  placeholder="+57 300 000 0000")
                    _err(errors, "phone")
                c1, c2, c3 = st.columns([0.9, 1.4, 1])
                with c1:
                    st.selectbox("Día de nacimiento", range(1, 32), key="reg_birth_day", index=None,
                                 placeholder="Día")
                with c2:
                    st.selectbox("Mes", range(1, 13), key="reg_birth_month", index=None,
                                 placeholder="Mes", format_func=lambda m: MONTHS[m - 1])
                with c3:
                    st.selectbox("Año", _birth_years(), key="reg_birth_year", index=None,
                                 placeholder="Año")
                _err(errors, "birth_date")

            with st.container(key="grp-pink"):
                theme.group_title("ecg_heart", "Salud", "demo")
                c1, c2 = st.columns([0.7, 1])
                with c1:
                    st.selectbox("Sangre", accounts.BLOOD_TYPES, key="reg_blood_type", index=None,
                                 placeholder="Elige")
                    _err(errors, "blood_type")
                with c2:
                    st.text_input("Alergias", key="reg_allergies", max_chars=200, autocomplete="off",
                                  placeholder="Ninguna")
                    _err(errors, "allergies")
                st.text_input("Condición crónica", key="reg_chronic_condition", max_chars=200,
                              autocomplete="off", placeholder="Ninguna")
                _err(errors, "chronic_condition")

            with st.container(key="grp-lilac"):
                theme.group_title("credit_card", "Crédito", "demo")
                c1, c2 = st.columns(2)
                with c1:
                    # Sin min/max: si el navegador bloquea un valor fuera de rango, el envío
                    # falla en silencio. El rango lo valida el servidor y el error sale aquí.
                    st.number_input("Puntaje (150–950)", key="reg_credit_score", value=None, step=1)
                    _err(errors, "credit_score")
                    st.number_input("Deuda (COP)", key="reg_outstanding_debt", value=None, step=100_000.0,
                                    format="%.0f")
                    _err(errors, "outstanding_debt")
                with c2:
                    st.number_input("Ingreso mensual (COP)", key="reg_monthly_income", value=None,
                                    step=50_000.0, format="%.0f")
                    _err(errors, "monthly_income")

            with st.container(key="demo-actions", horizontal=True, vertical_alignment="center",
                              horizontal_alignment="distribute"):
                st.form_submit_button("Atrás", type="tertiary", icon=":material/arrow_back:", on_click=_on_reg_back)
                st.form_submit_button("Crear cuenta", type="primary", on_click=_on_register)
    with right:
        register_aside(1)


def view_enrollment(user_id: int) -> None:
    try:
        ticket = accounts.get_pending_enrollment(user_id)
    except Exception as exc:
        log.error("event=enroll_view_unavailable error=%s", type(exc).__name__)
        theme.notice(SERVICE_ERROR, "error")
        return
    if ticket is None:
        session.end_enrollment()
        st.session_state[VIEW] = "login"
        _flash(f"El QR venció o se agotaron los intentos. {RESTART_HINT}", "warn")
        st.rerun()

    left, right = st.columns([1, 1.12], gap="large")
    with left, st.container(key="auth-main"):
        theme.logo()
        theme.heading("Configura tu autenticador",
                      "Paso 3 de 3 · Escanea el QR con Google Authenticator, Aegis, 1Password o la app "
                      "que uses y escribe el código que aparece.")
        _show_flash()
        png = base64.b64encode(otp.qr_png(ticket.uri)).decode("ascii")
        with st.container(key="qr"):
            theme.qr(png, ticket.username)
        mins = theme.minutes_left(ticket.expires_at)
        theme.boxes([
            ("Vence", f"en {mins} min" if mins else "en menos de 1 min"),
            ("Intentos", f"{ticket.attempts_left} de {accounts.ENROLL_MAX_ATTEMPTS}"),
        ])
        theme.secret_key(otp.group_secret(ticket.secret))
        with st.form("enroll", border=False, enter_to_submit=True):
            st.text_input("Código de la app", key="otp_enroll", max_chars=6, placeholder="000000",
                          autocomplete="one-time-code", icon=":material/pin:")
            st.form_submit_button("Activar", type="primary", on_click=_on_confirm_enroll, width="stretch")
        with st.container(key="switch", horizontal=True, vertical_alignment="center", gap="small"):
            theme.text_row("¿Prefieres hacerlo después?")
            st.button("Cancelar", key="cancel_enroll", type="tertiary", on_click=_on_cancel_enroll)
    with right:
        register_aside(2)


# --------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------

enroll_uid = session.enrollment_user_id()
view = st.session_state.get(VIEW, "login")

with st.container(key=f"auth-{'enroll' if enroll_uid is not None else view}"):
    if enroll_uid is not None:
        view_enrollment(enroll_uid)
    elif view == "register":
        view_register()
    elif view == "demo":
        if (reg := _fresh(REG_PENDING, REG_TTL_S)) is not None:
            view_demo(reg)
        else:  # pasaron más de 15 minutos desde el paso 1
            _stash_demo()
            st.session_state[VIEW] = "register"
            _flash("Pasó demasiado tiempo. Vuelve a escribir los datos de la cuenta.", "warn")
            view_register()
    elif view == "code" and (pending := _fresh(PENDING, PENDING_TTL_S)) is not None:
        view_code(pending)
    else:
        if view == "code":  # pasaron más de cinco minutos entre los dos pasos
            st.session_state[VIEW] = "login"
            _flash("La verificación expiró. Vuelve a escribir tus datos.", "warn")
        view_login()

_show_toast()
