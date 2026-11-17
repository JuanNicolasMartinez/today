"""Registro, enrolamiento, inicio de sesión con tres factores, OTP y límites."""

import itertools
import logging
import threading

import pytest

from conftest import BASE_NOW, registration
from web_app.security import otp
from web_app.services import accounts

PW = "Faro-del-norte 2291"


def _code(ticket, offset_steps=1):
    """Código del intervalo BASE + offset (el de BASE ya se consumió al enrolar)."""
    step = otp.current_step(BASE_NOW) + offset_steps
    return otp.code_at_step(ticket.secret, step), step * 30 + 5


# --- Registro y duplicados ---------------------------------------------------


def test_registro_guarda_cuenta_y_perfil(clean, owner):
    ticket = accounts.register(registration("Ana.Prueba"))
    row = owner.execute(
        "SELECT username, email, password_hash, otp_enabled, otp_secret_enc, otp_pending_secret_enc"
        " FROM today.app_user WHERE id = %s",
        (ticket.user_id,),
    ).fetchone()
    username, email, pw_hash, enabled, active_secret, pending = row
    assert username == "ana.prueba"  # se normaliza a minúsculas
    assert email == "ana.prueba@example.test"
    assert pw_hash.startswith("$argon2id$") and PW not in pw_hash
    assert enabled is False and active_secret is None
    assert pending is not None and ticket.secret.encode() not in bytes(pending)
    assert owner.execute("SELECT count(*) FROM today.user_profile WHERE user_id = %s", (ticket.user_id,)).fetchone()[0] == 1
    assert ticket.uri.startswith("otpauth://totp/")


def test_usuario_duplicado_sin_importar_mayusculas(clean, owner):
    accounts.register(registration("ana.prueba"))
    with pytest.raises(accounts.RegistrationError) as exc:
        accounts.register(registration("ANA.Prueba", email="otra@example.test"))
    assert set(exc.value.errors) == {"username"}
    assert owner.execute("SELECT count(*) FROM today.app_user").fetchone()[0] == 1


def test_correo_duplicado(clean, owner):
    accounts.register(registration("ana.prueba", email="Ana@Example.test"))
    with pytest.raises(accounts.RegistrationError) as exc:
        accounts.register(registration("otra.persona", email="ana@example.TEST"))
    assert set(exc.value.errors) == {"email"}
    # Sin filas huérfanas en el perfil tras el fallo.
    assert owner.execute("SELECT count(*) FROM today.user_profile").fetchone()[0] == 1


def test_validacion_en_servidor(clean):
    bad = registration(
        "a",
        email="no-es-correo",
        password="corta",
        password_confirm="otra",
        credit_score=10,
        blood_type="Z+",
        phone="abc",
        monthly_income=-5,
        birth_date=None,
    )
    with pytest.raises(accounts.RegistrationError) as exc:
        accounts.register(bad)
    assert {"username", "email", "password", "password_confirm", "credit_score",
            "blood_type", "phone", "monthly_income", "birth_date"} <= set(exc.value.errors)


# --- Enrolamiento --------------------------------------------------------------


def test_enrolamiento_activa_y_cifra(make_user, owner):
    ticket = make_user()
    enabled, secret_enc, pending, last_step = owner.execute(
        "SELECT otp_enabled, otp_secret_enc, otp_pending_secret_enc, otp_last_step FROM today.app_user WHERE id = %s",
        (ticket.user_id,),
    ).fetchone()
    assert enabled and pending is None
    assert ticket.secret.encode() not in bytes(secret_enc)
    assert last_step == otp.current_step(BASE_NOW)  # el código del enrolamiento queda consumido


def test_enrolamiento_limite_de_intentos(make_user):
    ticket = make_user(enroll=False)
    good = otp.code_at_step(ticket.secret, otp.current_step(BASE_NOW))
    wrong = "000000" if good != "000000" else "111111"
    for left in (4, 3, 2, 1):
        r = accounts.confirm_enrollment(ticket.user_id, wrong, now=BASE_NOW)
        assert r.status is accounts.EnrollStatus.INVALID and r.attempts_left == left
    r = accounts.confirm_enrollment(ticket.user_id, wrong, now=BASE_NOW)
    assert r.status is accounts.EnrollStatus.EXHAUSTED
    assert accounts.get_pending_enrollment(ticket.user_id) is None
    # Ni siquiera el código correcto sirve ya: hay que reiniciar.
    assert accounts.confirm_enrollment(ticket.user_id, good, now=BASE_NOW).status is accounts.EnrollStatus.NOT_PENDING


def test_enrolamiento_vencido(make_user, owner):
    ticket = make_user(enroll=False)
    owner.execute("UPDATE today.app_user SET otp_pending_expires_at = now() - interval '1 second' WHERE id = %s",
                  (ticket.user_id,))
    good = otp.code_at_step(ticket.secret, otp.current_step(BASE_NOW))
    assert accounts.confirm_enrollment(ticket.user_id, good, now=BASE_NOW).status is accounts.EnrollStatus.EXPIRED


def test_reinicio_de_enrolamiento(make_user):
    pending = make_user("sin.otp", enroll=False)
    assert accounts.start_enrollment("sin.otp", "otra-clave-mala 1") is None
    fresh = accounts.start_enrollment("SIN.OTP", PW)
    assert fresh is not None and fresh.secret != pending.secret
    # Una cuenta con OTP activo no puede reenrolarse con solo la contraseña.
    make_user("con.otp")
    assert accounts.start_enrollment("con.otp", PW) is None


# --- Inicio de sesión: combinaciones de los tres campos -------------------------

COMBOS = list(itertools.product([True, False], repeat=3))


@pytest.mark.parametrize("user_ok, pw_ok, code_ok", COMBOS, ids=lambda v: "ok" if v else "mal")
def test_login_exige_los_tres_factores(make_user, owner, user_ok, pw_ok, code_ok):
    ticket = make_user()
    good_code, now = _code(ticket)
    username = "ana.prueba" if user_ok else "no.existe"
    password = PW if pw_ok else PW + "x"
    code = good_code if code_ok else f"{(int(good_code) + 1) % 1_000_000:06d}"
    user = accounts.authenticate(username, password, code, now=now)
    if user_ok and pw_ok and code_ok:
        assert user is not None and user.id == ticket.user_id
    else:
        assert user is None
    if user_ok and not (pw_ok and code_ok):
        failed = owner.execute("SELECT failed_attempts FROM today.app_user WHERE id = %s", (ticket.user_id,)).fetchone()[0]
        assert failed == 1


def test_login_campos_vacios(make_user):
    ticket = make_user()
    code, now = _code(ticket)
    assert accounts.authenticate("ana.prueba", PW, "", now=now) is None
    assert accounts.authenticate("ana.prueba", "", code, now=now) is None
    assert accounts.authenticate("", PW, code, now=now) is None


def test_login_sin_otp_activo_falla(make_user):
    ticket = make_user(enroll=False)
    code = otp.code_at_step(ticket.secret, otp.current_step(BASE_NOW))
    assert accounts.authenticate("ana.prueba", PW, code, now=BASE_NOW) is None


def test_otp_con_cero_inicial(make_user):
    ticket = make_user()
    base = otp.current_step(BASE_NOW) + 1
    step = next(s for s in range(base, base + 5000) if otp.code_at_step(ticket.secret, s).startswith("0"))
    code = otp.code_at_step(ticket.secret, step)
    assert code[0] == "0" and len(code) == 6
    assert accounts.authenticate("ana.prueba", PW, code, now=step * 30 + 3) is not None


def test_otp_vencido(make_user):
    ticket = make_user()
    s = otp.current_step(BASE_NOW) + 10
    old = otp.code_at_step(ticket.secret, s)
    window = {otp.code_at_step(ticket.secret, x) for x in (s + 1, s + 2, s + 3)}
    if old in window:
        pytest.skip("colisión improbable de códigos")
    # A los 60 s el código de s ya está fuera de la ventana (±1 intervalo).
    assert accounts.authenticate("ana.prueba", PW, old, now=(s + 2) * 30 + 1) is None
    # El intervalo inmediatamente anterior sí se acepta (desfase de reloj).
    assert accounts.authenticate("ana.prueba", PW, otp.code_at_step(ticket.secret, s + 1), now=(s + 2) * 30 + 1)


def test_otp_reutilizado(make_user, owner):
    ticket = make_user()
    code, now = _code(ticket, 3)
    assert accounts.authenticate("ana.prueba", PW, code, now=now) is not None
    assert accounts.authenticate("ana.prueba", PW, code, now=now) is None  # mismo código
    assert accounts.authenticate("ana.prueba", PW, code, now=now + 20) is None
    # Un código de un intervalo anterior aún dentro de la ventana tampoco.
    prev = otp.code_at_step(ticket.secret, otp.current_step(now) - 1)
    assert accounts.authenticate("ana.prueba", PW, prev, now=now) is None
    # El código del enrolamiento tampoco sirve para iniciar sesión.
    enroll_code = otp.code_at_step(ticket.secret, otp.current_step(BASE_NOW))
    assert accounts.authenticate("ana.prueba", PW, enroll_code, now=BASE_NOW) is None


def test_otp_reutilizado_en_paralelo(make_user):
    """Dos intentos simultáneos con el mismo código: solo uno crea sesión."""
    ticket = make_user()
    code, now = _code(ticket, 5)
    barrier = threading.Barrier(4)
    results = []

    def attempt():
        barrier.wait()
        results.append(accounts.authenticate("ana.prueba", PW, code, now=now))

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1


# --- Límite de intentos persistente --------------------------------------------


def test_bloqueo_por_intentos_persistente(make_user, owner):
    from web_app import db

    ticket = make_user()
    for _ in range(accounts.MAX_LOGIN_ATTEMPTS):
        assert accounts.authenticate("ana.prueba", "clave-incorrecta 1", "123456", now=BASE_NOW + 30) is None
    failed, locked = owner.execute(
        "SELECT failed_attempts, locked_until > now() FROM today.app_user WHERE id = %s", (ticket.user_id,)
    ).fetchone()
    assert failed == accounts.MAX_LOGIN_ATTEMPTS and locked

    db.close_pool()  # "reinicio" de la app: el bloqueo vive en PostgreSQL
    code, now = _code(ticket, 2)
    assert accounts.authenticate("ana.prueba", PW, code, now=now) is None  # bloqueada aun con todo correcto

    owner.execute("UPDATE today.app_user SET locked_until = now() - interval '1 second' WHERE id = %s",
                  (ticket.user_id,))
    code, now = _code(ticket, 3)
    assert accounts.authenticate("ana.prueba", PW, code, now=now) is not None
    failed, locked_until = owner.execute(
        "SELECT failed_attempts, locked_until FROM today.app_user WHERE id = %s", (ticket.user_id,)
    ).fetchone()
    assert failed == 0 and locked_until is None


def test_bloqueo_con_intentos_en_paralelo(make_user, owner):
    ticket = make_user()
    barrier = threading.Barrier(10)

    def attempt():
        barrier.wait()
        accounts.authenticate("ana.prueba", "clave-incorrecta 1", "123456", now=BASE_NOW + 30)

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    failed, locked = owner.execute(
        "SELECT failed_attempts, locked_until > now() FROM today.app_user WHERE id = %s", (ticket.user_id,)
    ).fetchone()
    # Sin actualizaciones perdidas: exactamente el máximo y la cuenta bloqueada.
    assert failed == accounts.MAX_LOGIN_ATTEMPTS and locked


# --- Logs sin secretos -----------------------------------------------------------


def test_logs_sin_secretos(make_user, caplog):
    caplog.set_level(logging.DEBUG)
    ticket = make_user("log.prueba", email="log.prueba@example.test", document_id="99887766")
    code, now = _code(ticket)
    accounts.authenticate("log.prueba", PW, code, now=now)
    accounts.authenticate("log.prueba", "otra-clave-mala 9", code, now=now)
    accounts.authenticate("nadie.aqui", PW, code, now=now)
    text = caplog.text
    assert "event=auth_ok" in text and "event=auth_failed" in text
    for secret in (PW, "otra-clave-mala", code, ticket.secret, "log.prueba@example.test",
                   "99887766", "nadie.aqui", "log.prueba"):
        assert secret not in text
