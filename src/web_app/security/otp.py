"""TOTP (RFC 6238) con pyotp y cifrado de semillas con AES-256-GCM.

* Una semilla aleatoria de 160 bits por usuario (``pyotp.random_base32``).
* La semilla se cifra antes de guardarla. El id del usuario va como dato
  asociado (AAD): una semilla copiada a otra fila no se puede descifrar.
* Los códigos se tratan siempre como texto de seis dígitos, nunca como
  número, para conservar los ceros iniciales.
* ``matching_step`` devuelve el intervalo (paso de 30 s) que coincide. El
  servicio de cuentas guarda ese intervalo y rechaza cualquier código cuyo
  intervalo no sea mayor que el último aceptado.
"""

from __future__ import annotations

import hmac
import io
import os
import re
import time

import pyotp
import qrcode
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DIGITS = 6
INTERVAL = 30
# Se acepta el intervalo actual y uno a cada lado (±30 s de desfase de reloj).
VALID_WINDOW = 1

_FORMAT_VERSION = b"\x01"
_NONCE_LEN = 12
_CODE_RE = re.compile(r"^[0-9]{6}$")


class SecretDecryptionError(RuntimeError):
    pass


def new_secret() -> str:
    return pyotp.random_base32()  # 32 caracteres base32 = 160 bits


def _aad(user_id: int) -> bytes:
    return f"today:otp-secret:v1:user:{user_id}".encode()


def encrypt_secret(key: bytes, secret: str, user_id: int) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("ascii"), _aad(user_id))
    return _FORMAT_VERSION + nonce + ciphertext


def decrypt_secret(key: bytes, blob: bytes, user_id: int) -> str:
    blob = bytes(blob)
    if not blob.startswith(_FORMAT_VERSION) or len(blob) <= 1 + _NONCE_LEN:
        raise SecretDecryptionError("Formato de semilla desconocido.")
    nonce = blob[1 : 1 + _NONCE_LEN]
    try:
        plain = AESGCM(key).decrypt(nonce, blob[1 + _NONCE_LEN :], _aad(user_id))
    except InvalidTag as exc:
        raise SecretDecryptionError("No se pudo descifrar la semilla.") from exc
    return plain.decode("ascii")


def normalize_code(raw: object) -> str | None:
    """Devuelve el código como texto de 6 dígitos o ``None`` si no es válido."""
    if not isinstance(raw, str):
        return None
    code = raw.replace(" ", "").strip()
    return code if _CODE_RE.fullmatch(code) else None


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // INTERVAL)


def code_at_step(secret: str, step: int) -> str:
    return pyotp.TOTP(secret, digits=DIGITS, interval=INTERVAL).generate_otp(step)


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """Intervalo que corresponde a ``code`` dentro de la ventana, o ``None``.

    Recorre toda la ventana sin salir antes para no filtrar por tiempo cuál
    intervalo coincidió.
    """
    normalized = normalize_code(code)
    if normalized is None:
        return None
    base = current_step(now)
    found: int | None = None
    for step in range(base - VALID_WINDOW, base + VALID_WINDOW + 1):
        if hmac.compare_digest(code_at_step(secret, step), normalized) and found is None:
            found = step
    return found


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret, digits=DIGITS, interval=INTERVAL).provisioning_uri(
        name=account, issuer_name=issuer
    )


def qr_png(data: str, *, dark: str = "#2a2839", light: str = "#ffffff") -> bytes:
    qr = qrcode.QRCode(
        version=None,
        box_size=10,
        border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=dark, back_color=light)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def group_secret(secret: str) -> str:
    """Semilla en bloques de 4 para escribirla a mano."""
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))
