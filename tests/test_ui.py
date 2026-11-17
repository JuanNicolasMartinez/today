"""Pruebas de la interfaz con streamlit.testing (AppTest) contra la app real."""

import datetime as dt
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from web_app.security import otp
from web_app.services import accounts

MAIN = str(Path(__file__).resolve().parents[1] / "src" / "web_app" / "main.py")
PW = "Faro-del-norte 2291"
LOGIN = "FormSubmitter:login-Continuar"
VERIFY = "FormSubmitter:otp-Verificar e ingresar"
TEAM_PAGES = ["all_pages/3_A_page.py", "all_pages/4_B_page.py", "all_pages/5_C_page.py"]
SECTION_PAGES = ["all_pages/7_personal_page.py", "all_pages/8_salud_page.py",
                 "all_pages/9_credito_page.py", "all_pages/10_seguridad_page.py"]


def _app(user_id: int | None = None) -> AppTest:
    at = AppTest.from_file(MAIN, default_timeout=30)
    if user_id is not None:
        now = time.time()
        at.session_state["_auth"] = {"user_id": user_id, "issued": now, "seen": now}
    at.run()
    assert not at.exception, at.exception
    return at


def _html(at: AppTest) -> str:
    return "\n".join(str(getattr(e, "proto", e)) for e in at.get("html"))


def _credentials(at: AppTest, user: str = "ana.prueba", password: str = PW) -> None:
    at.text_input(key="login_user").input(user)
    at.text_input(key="login_pass").input(password)
    at.button(key=LOGIN).click().run()
    assert not at.exception, at.exception


def _code(at: AppTest, code: str) -> None:
    at.text_input(key="otp_login").input(code)
    at.button(key=VERIFY).click().run()
    assert not at.exception, at.exception


def _failed_attempts(owner, user_id: int) -> int:
    return owner.execute("SELECT failed_attempts FROM today.app_user WHERE id = %s", (user_id,)).fetchone()[0]


def _enroll_now(ticket) -> None:
    """Activa el OTP con el intervalo anterior al actual (reloj real)."""
    before = time.time() - otp.INTERVAL
    code = otp.code_at_step(ticket.secret, otp.current_step(before))
    assert accounts.confirm_enrollment(ticket.user_id, code, now=before).status is accounts.EnrollStatus.ACTIVATED


# --- Sin sesión: solo existe el acceso ------------------------------------------


def test_sin_sesion_abre_en_el_inicio_de_sesion(clean):
    at = _app()
    assert at.text_input(key="login_user") is not None
    assert "Inicia sesión" in _html(at)
    for name in ("Nicolás Martínez", "Laurence Santamaría", "María José Barreto", "Natali Alba", "Daniel Camacho"):
        assert name in _html(at)
    # El código no se pide ni se muestra en el primer paso.
    assert not [w for w in at.text_input if w.key == "otp_login"]
    assert "otp_login" not in at.session_state


@pytest.mark.parametrize("page", ["all_pages/6_panel_page.py", *SECTION_PAGES, *TEAM_PAGES])
def test_sin_sesion_no_hay_otras_paginas(clean, page):
    """Sin sesión, la navegación solo registra la página de acceso."""
    at = _app()
    with pytest.raises(ValueError, match="Known pages: .*2_auth_page.py'\\]"):
        at.switch_page(page)
    assert "Hola," not in _html(at)


# --- Inicio de sesión en dos pasos -----------------------------------------------


def test_paso1_exige_usuario_y_contrasena(make_user):
    make_user()
    at = _app()
    at.text_input(key="login_user").input("ana.prueba")
    at.button(key=LOGIN).click().run()
    assert "Escribe tu usuario y tu contraseña." in _html(at)
    assert "_login_pending" not in at.session_state


def test_paso1_no_verifica_ni_cuenta_intentos(make_user, owner):
    """Una contraseña errónea también pasa al paso 2: el paso 1 no sirve para probar contraseñas."""
    ticket = make_user()
    at = _app()
    _credentials(at, password="Contraseña equivocada 1")
    assert at.text_input(key="otp_login") is not None
    assert "Verificación en dos pasos" in _html(at)
    # El campo de contraseña se vació al pasar de paso.
    assert "login_pass" not in at.session_state or at.session_state["login_pass"] == ""
    assert _failed_attempts(owner, ticket.user_id) == 0

    _code(at, otp.code_at_step(ticket.secret, otp.current_step()))
    assert "_auth" not in at.session_state
    assert "No pudimos verificar tus datos" in _html(at)
    assert "_login_pending" not in at.session_state
    assert _failed_attempts(owner, ticket.user_id) == 1


def test_paso2_codigo_vacio_no_consume_el_paso(make_user):
    make_user()
    at = _app()
    _credentials(at)
    at.button(key=VERIFY).click().run()
    assert "Escribe el código de seis dígitos." in _html(at)
    assert "_login_pending" in at.session_state


def test_paso2_error_generico(make_user, owner):
    ticket = make_user()
    at = _app()
    _credentials(at)
    _code(at, "000000")
    assert "_auth" not in at.session_state
    assert "No pudimos verificar tus datos" in _html(at)
    assert "Inicia sesión" in _html(at)  # vuelve al paso 1
    assert "_login_pending" not in at.session_state
    assert _failed_attempts(owner, ticket.user_id) == 1


def test_paso2_vence(make_user):
    make_user()
    at = _app()
    _credentials(at)
    pending = dict(at.session_state["_login_pending"])
    pending["at"] -= 6 * 60
    at.session_state["_login_pending"] = pending
    at.run()
    assert "La verificación expiró" in _html(at)
    assert "_login_pending" not in at.session_state


def test_login_completo_y_cierre_de_sesion(make_user):
    ticket = make_user(enroll=False)
    _enroll_now(ticket)
    at = _app()
    _credentials(at)
    _code(at, otp.code_at_step(ticket.secret, otp.current_step()))
    assert at.session_state["_auth"]["user_id"] == ticket.user_id
    assert "_login_pending" not in at.session_state
    assert "Hola," in _html(at)  # llegó al resumen

    at.button(key="logout").click().run()
    assert not at.exception, at.exception
    assert "_auth" not in at.session_state
    assert "Inicia sesión" in _html(at)


def test_configurar_autenticador_desde_el_paso2(make_user):
    make_user(enroll=False)
    at = _app()
    _credentials(at)
    at.button(key="start_enroll").click().run()
    assert not at.exception, at.exception
    html = _html(at)
    assert "Código QR para ana.prueba" in html and "data:image/png;base64," in html


def test_configurar_autenticador_rechaza_cuenta_con_otp(make_user):
    make_user()  # ya tiene el OTP activo
    at = _app()
    _credentials(at)
    at.button(key="start_enroll").click().run()
    assert "Código QR" not in _html(at)
    assert "No fue posible configurar el autenticador" in _html(at)


# --- Registro en tres pasos ------------------------------------------------------

NEXT = "FormSubmitter:register-Siguiente"
CREATE = "FormSubmitter:demo-Crear cuenta"
BACK = "FormSubmitter:demo-Atrás"
FILL = "FormSubmitter:demo-Llenar con datos ficticios"


def _account_step(at: AppTest, username: str = "qr.propio", email: str | None = None, password: str = PW) -> None:
    at.text_input(key="reg_username").input(username)
    at.text_input(key="reg_email").input(email or f"{username}@example.test")
    at.text_input(key="reg_password").input(password)
    at.text_input(key="reg_password_confirm").input(password)
    at.button(key=NEXT).click().run()
    assert not at.exception, at.exception


def _demo_step(at: AppTest) -> None:
    for key, value in {
        "reg_full_name": "Quinto Ficticio", "reg_document_id": "55667788",
        "reg_phone": "+57 300 000 1111", "reg_city": "Tunja",
        "reg_allergies": "", "reg_chronic_condition": "",
    }.items():
        at.text_input(key=key).input(value)
    at.date_input(key="reg_birth_date").set_value(dt.date(1990, 1, 2))
    at.selectbox(key="reg_blood_type").select("A+")
    at.number_input(key="reg_credit_score").set_value(640)
    at.number_input(key="reg_monthly_income").set_value(2_500_000.0)
    at.number_input(key="reg_outstanding_debt").set_value(0.0)


def _to_register(at: AppTest) -> None:
    at.button(key="to_register").click().run()
    assert "Crea tu cuenta" in _html(at)


def _accounts(owner) -> int:
    return owner.execute("SELECT count(*) FROM today.app_user").fetchone()[0]


def test_qr_solo_en_la_sesion_que_registra(clean):
    at = _app()
    _to_register(at)
    _account_step(at)
    assert "Datos de demostración" in _html(at)
    _demo_step(at)
    at.button(key=CREATE).click().run()
    assert not at.exception, at.exception
    html = _html(at)
    assert "Código QR para qr.propio" in html and "data:image/png;base64," in html
    assert "_reg_account" not in at.session_state  # la contraseña pendiente ya no está

    other = _app()  # otra sesión de navegador
    assert "Código QR" not in _html(other)
    assert "_enroll_user_id" not in other.session_state


def test_registro_paso1_valida_y_borra_la_contrasena(clean, owner):
    at = _app()
    _to_register(at)
    _account_step(at, username="x", email="mal")
    assert "De 3 a 32 caracteres" in _html(at) and "Escribe un correo válido." in _html(at)
    assert at.text_input(key="reg_password").value == ""
    assert "Crea tu cuenta" in _html(at)  # sigue en el paso 1
    assert "_reg_account" not in at.session_state


def test_registro_paso1_no_crea_nada_en_la_base(clean, owner):
    at = _app()
    _to_register(at)
    _account_step(at)
    assert "Datos de demostración" in _html(at)
    assert _accounts(owner) == 0


def test_registro_llenar_con_datos_ficticios(clean, owner):
    at = _app()
    _to_register(at)
    _account_step(at)
    at.button(key=FILL).click().run()
    assert at.text_input(key="reg_full_name").value
    at.button(key=CREATE).click().run()
    assert not at.exception, at.exception
    assert "Código QR para qr.propio" in _html(at)
    assert _accounts(owner) == 1


def test_registro_atras_conserva_datos_y_pide_la_contrasena(clean):
    at = _app()
    _to_register(at)
    _account_step(at)
    at.text_input(key="reg_full_name").input("Quinto Ficticio")
    at.button(key=BACK).click().run()
    assert not at.exception, at.exception
    assert at.text_input(key="reg_username").value == "qr.propio"
    assert at.text_input(key="reg_password").value == ""
    assert "_reg_account" not in at.session_state
    assert "Vuelve a escribir la contraseña" in _html(at)
    _account_step(at)
    assert at.text_input(key="reg_full_name").value == "Quinto Ficticio"


def test_registro_puntaje_fuera_de_rango_muestra_el_error(clean, owner):
    """Los números no tienen límites en el navegador: el servidor valida y avisa en el campo."""
    at = _app()
    _to_register(at)
    _account_step(at)
    _demo_step(at)
    at.number_input(key="reg_credit_score").set_value(123)
    at.button(key=CREATE).click().run()
    assert not at.exception, at.exception
    assert "Entre 150 y 950." in _html(at)
    assert "Datos de demostración" in _html(at)  # sigue en el paso 2
    assert "_reg_account" in at.session_state
    assert _accounts(owner) == 0


def test_registro_usuario_duplicado_vuelve_al_paso1(make_user, owner):
    make_user()  # ana.prueba
    at = _app()
    _to_register(at)
    _account_step(at, username="ANA.prueba", email="otra.ana@example.test")
    _demo_step(at)
    at.button(key=CREATE).click().run()
    assert not at.exception, at.exception
    assert "Crea tu cuenta" in _html(at)
    assert "Ese nombre de usuario no está disponible." in _html(at)
    assert "_reg_account" not in at.session_state
    assert _accounts(owner) == 1


# --- Panel ----------------------------------------------------------------------


def test_resumen_cualquier_cuenta_ve_descarga(make_user):
    ticket = make_user()
    at = _app(ticket.user_id)
    assert "Hola," in _html(at)
    assert "Descargar usuarios" in _html(at)
    assert len(at.get("download_button")) == 1


def test_sin_sesion_no_hay_descarga(clean):
    at = _app()
    assert len(at.get("download_button")) == 0
    assert "Descargar usuarios" not in _html(at)


@pytest.mark.parametrize("page", SECTION_PAGES)
def test_secciones_de_la_cuenta_cargan_sin_descarga(make_user, page):
    ticket = make_user()
    at = _app(ticket.user_id)
    at.switch_page(page).run()
    assert not at.exception, at.exception
    assert len(at.get("download_button")) == 0  # la descarga solo está en el resumen


@pytest.mark.parametrize("page", TEAM_PAGES)
def test_paginas_de_equipos_cargan_con_sesion(make_user, page):
    ticket = make_user()
    at = _app(ticket.user_id)
    at.switch_page(page).run()
    assert not at.exception, at.exception
    assert any("Equipo" in t.value for t in at.title)
