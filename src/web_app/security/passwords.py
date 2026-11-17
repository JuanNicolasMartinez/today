"""Política de contraseñas y hash Argon2id.

Política (se valida en el servidor, ver ``check_policy``):

* Se normaliza a Unicode NFKC antes de validar y de calcular el hash.
* Longitud: entre 12 y 128 caracteres. El tope evita abusar del coste de hash.
* Debe incluir al menos una letra y al menos un número o un símbolo.
* Al menos 6 caracteres distintos (rechaza ``aaaaaaaaaaa1``).
* No puede contener el nombre de usuario ni la parte local del correo.
* No puede ser una contraseña común ni una palabra común con números o
  símbolos alrededor (``Password2025!``, ``Contraseña123``).
* Sin caracteres de control.

Hash: Argon2id (argon2-cffi) con el perfil de bajo consumo de memoria de
RFC 9106: t=3, m=64 MiB, p=4, sal aleatoria de 16 bytes por contraseña. El
resultado incluye algoritmo, parámetros y sal en formato PHC.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128
MIN_DISTINCT = 6

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Palabras base habituales en contraseñas débiles (en minúsculas, sin números).
_COMMON_WORDS = frozenset(
    {
        "password", "passwrd", "psswrd", "pssword", "passwd", "contraseña",
        "contrasena", "contrasea", "cntrsea", "clave",
        "qwerty", "qwertyuiop", "asdfgh", "asdfghjkl", "zxcvbnm", "abc", "abcdef",
        "admin", "administrator", "administrador", "root", "user", "usuario",
        "welcome", "bienvenido", "bienvenida", "letmein", "iloveyou", "teamo",
        "colombia", "bogota", "medellin", "dragon", "monkey", "football",
        "futbol", "sunshine", "princess", "superman", "batman", "today", "nuu",
        "secret", "secreto", "changeme", "cambiame",
    }
)
_COMMON_PASSWORDS = frozenset(
    {
        "123456789012", "1234567890123", "12345678901234", "111111111111",
        "000000000000", "123123123123", "qwerty123456", "1q2w3e4r5t6y",
        "1qaz2wsx3edc", "qazwsxedcrfv", "zaq12wsxcde3", "password1234",
        "passw0rd1234", "abc123456789", "iloveyou1234", "987654321098",
    }
)


class PasswordPolicyError(ValueError):
    """La contraseña no cumple la política. ``str(exc)`` es apto para la UI."""


def normalize(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def check_policy(password: str, *, username: str = "", email: str = "") -> str:
    """Valida y devuelve la contraseña normalizada, o lanza PasswordPolicyError."""
    pw = normalize(password)
    if len(pw) < MIN_LENGTH:
        raise PasswordPolicyError(f"Usa al menos {MIN_LENGTH} caracteres.")
    if len(pw) > MAX_LENGTH:
        raise PasswordPolicyError(f"Usa como máximo {MAX_LENGTH} caracteres.")
    if any(unicodedata.category(ch) == "Cc" for ch in pw):
        raise PasswordPolicyError("No uses caracteres de control.")
    if not any(ch.isalpha() for ch in pw):
        raise PasswordPolicyError("Incluye al menos una letra.")
    if not any(not ch.isalpha() for ch in pw):
        raise PasswordPolicyError("Incluye al menos un número o un símbolo.")
    if len(set(pw)) < MIN_DISTINCT:
        raise PasswordPolicyError("Usa más caracteres distintos.")

    folded = pw.casefold()
    for ident in (username.strip().casefold(), email.strip().casefold().split("@")[0]):
        if len(ident) >= 3 and ident in folded:
            raise PasswordPolicyError("No incluyas tu usuario ni tu correo.")

    letters_only = "".join(ch for ch in folded if ch.isalpha())
    if folded in _COMMON_PASSWORDS or letters_only in _COMMON_WORDS:
        raise PasswordPolicyError("Es una contraseña demasiado común.")
    return pw


def hash_password(password: str) -> str:
    return _hasher.hash(normalize(password))


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("today-dummy-password-for-timing")


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Compara en tiempo similar exista o no la cuenta."""
    target = stored_hash or _dummy_hash()
    try:
        ok = _hasher.verify(target, normalize(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
