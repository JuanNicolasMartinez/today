"""Configuración leída del entorno.

Los secretos (cadena de conexión y clave de cifrado de OTP) nunca se guardan en
el repositorio: llegan por variables de entorno. En el servidor se cargan desde
el ``EnvironmentFile`` de systemd; en local, con ``uv run --env-file .env``.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from functools import lru_cache


class ConfigError(RuntimeError):
    """Falta una variable obligatoria o tiene un formato inválido."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Falta la variable de entorno {name}.")
    return value


def decode_key(raw: str, name: str = "TODAY_OTP_ENCRYPTION_KEY") -> bytes:
    """Decodifica una clave AES-256 en base64 (urlsafe o estándar)."""
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ConfigError(f"{name} no es base64 válido.") from exc
    if len(key) != 32:
        raise ConfigError(f"{name} debe decodificar a 32 bytes (AES-256).")
    return key


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    otp_key: bytes
    otp_issuer: str
    app_role: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_require("TODAY_DATABASE_URL"),
        otp_key=decode_key(_require("TODAY_OTP_ENCRYPTION_KEY")),
        otp_issuer=os.environ.get("TODAY_OTP_ISSUER", "today").strip() or "today",
        app_role=os.environ.get("TODAY_APP_ROLE", "today_app").strip() or "today_app",
    )


def migrator_url() -> str:
    """Conexión con el rol dueño del esquema. Solo para migraciones y CLI."""
    return _require("TODAY_MIGRATOR_DATABASE_URL")


def app_role_name() -> str:
    return os.environ.get("TODAY_APP_ROLE", "today_app").strip() or "today_app"
