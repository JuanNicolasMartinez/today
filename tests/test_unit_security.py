"""Pruebas sin base de datos: contraseñas, TOTP, cifrado y neutralización CSV."""

import os

import pyotp
import pytest

from web_app.security import otp, passwords
from web_app.services import export

# --- Política de contraseñas ------------------------------------------------


@pytest.mark.parametrize(
    "pw, fragment",
    [
        ("Corta-1", "12 caracteres"),
        ("x" * 129 + "1", "128"),
        ("sololetrassinnada", "número o un símbolo"),
        ("123456789012345", "letra"),
        ("aaaaaaaaaaa1", "distintos"),
        ("ana.prueba-2291!", "usuario"),
        ("Password2025!!", "común"),
        ("Contraseña1234", "común"),
        ("qwerty123456", "común"),
        ("linea\x00nula-123", "control"),
    ],
)
def test_politica_rechaza(pw, fragment):
    with pytest.raises(passwords.PasswordPolicyError) as exc:
        passwords.check_policy(pw, username="ana.prueba", email="ana@example.test")
    assert fragment in str(exc.value)


@pytest.mark.parametrize("pw", ["Faro-del-norte 2291", "río.Magdalena#77", "una frase larga con 1 número"])
def test_politica_acepta(pw):
    assert passwords.check_policy(pw, username="ana.prueba", email="ana@example.test")


def test_argon2id_con_sal_distinta_y_verificacion():
    h1 = passwords.hash_password("Faro-del-norte 2291")
    h2 = passwords.hash_password("Faro-del-norte 2291")
    assert h1.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert h1 != h2  # sal aleatoria por hash
    assert "Faro-del-norte" not in h1
    assert passwords.verify_password(h1, "Faro-del-norte 2291")
    assert not passwords.verify_password(h1, "Faro-del-norte 2292")
    assert not passwords.verify_password(None, "Faro-del-norte 2291")
    assert not passwords.verify_password("no-es-un-hash", "x")


def test_normalizacion_nfkc():
    # "ﬁ" (ligadura) y "fi" deben producir la misma contraseña.
    h = passwords.hash_password("ﬁltro-seguro-2291")
    assert passwords.verify_password(h, "filtro-seguro-2291")


# --- Códigos TOTP como texto ----------------------------------------------


@pytest.mark.parametrize("raw, expected", [("012345", "012345"), (" 000 001 ", "000001"), ("999999", "999999")])
def test_codigo_conserva_ceros(raw, expected):
    assert otp.normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "1234567", "12a456", "", None, 12345, "١٢٣٤٥٦", "12345\n"])
def test_codigo_invalido(raw):
    assert otp.normalize_code(raw) is None


def test_matching_step_ventana_y_vencido():
    secret = pyotp.random_base32()
    now = 1_900_000_020.0
    step = otp.current_step(now)
    assert otp.matching_step(secret, otp.code_at_step(secret, step), now) == step
    assert otp.matching_step(secret, otp.code_at_step(secret, step - 1), now) == step - 1
    assert otp.matching_step(secret, otp.code_at_step(secret, step + 1), now) == step + 1
    # Dos intervalos atrás ya venció.
    old = otp.code_at_step(secret, step - 2)
    if old not in {otp.code_at_step(secret, s) for s in (step - 1, step, step + 1)}:
        assert otp.matching_step(secret, old, now) is None


def test_codigo_con_cero_inicial_coincide():
    secret = pyotp.random_base32()
    step = next(s for s in range(60_000_000, 60_001_000) if otp.code_at_step(secret, s).startswith("0"))
    code = otp.code_at_step(secret, step)
    assert len(code) == 6 and code[0] == "0"
    assert otp.matching_step(secret, code, step * 30 + 1) == step
    # Como número perdería el cero: no debe aceptarse.
    assert otp.matching_step(secret, str(int(code)), step * 30 + 1) is None


def test_cifrado_semilla_ligado_al_usuario():
    key = os.urandom(32)
    secret = otp.new_secret()
    blob = otp.encrypt_secret(key, secret, 7)
    assert secret.encode() not in blob
    assert otp.decrypt_secret(key, blob, 7) == secret
    with pytest.raises(otp.SecretDecryptionError):
        otp.decrypt_secret(key, blob, 8)  # copiada a otra fila
    with pytest.raises(otp.SecretDecryptionError):
        otp.decrypt_secret(os.urandom(32), blob, 7)  # otra clave
    tampered = bytearray(blob)
    tampered[-1] ^= 1
    with pytest.raises(otp.SecretDecryptionError):
        otp.decrypt_secret(key, bytes(tampered), 7)
    assert otp.encrypt_secret(key, secret, 7) != blob  # nonce aleatorio


# --- Neutralización CSV ----------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
        ("+57 300", "'+57 300"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\t=1", "'\t=1"),
        ("\r=1", "'\r=1"),
        ("  =1+1", "'  =1+1"),
        ("＝1+1", "'＝1+1"),
        ("Bogotá", "Bogotá"),
        ("", ""),
        ("a=b", "a=b"),
    ],
)
def test_neutraliza_formulas(value, expected):
    assert export.neutralize(value) == expected


def test_validate_account_solo_revisa_la_cuenta():
    from web_app.services.accounts import validate_account

    assert validate_account("ana.rojas", "ana@example.test", "Faro-del-norte 2291", "Faro-del-norte 2291") == {}
    errors = validate_account("x", "mal", "corta", "otra")
    assert set(errors) == {"username", "email", "password", "password_confirm"}
