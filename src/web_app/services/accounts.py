"""Registro, enrolamiento TOTP e inicio de sesión.

Todas las consultas son parametrizadas y se ejecutan con el rol de la
aplicación. Cada operación sensible corre en una transacción que bloquea la
fila de la cuenta (``SELECT ... FOR UPDATE``): los intentos simultáneos sobre
la misma cuenta se serializan, el contador de intentos no se puede saltar y un
intervalo TOTP aceptado se consume una sola vez.

Los registros (logs) solo llevan el evento y el id interno de la cuenta: nunca
contraseñas, códigos, semillas ni datos de formulario.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

import psycopg
from psycopg import errors as pg_errors

from web_app import db
from web_app.config import get_settings
from web_app.security import otp
from web_app.security.passwords import (
    PasswordPolicyError,
    check_policy,
    hash_password,
    needs_rehash,
    verify_password,
)

log = logging.getLogger("today.auth")

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT = dt.timedelta(minutes=15)
ENROLL_MAX_ATTEMPTS = 5
ENROLL_TTL = dt.timedelta(minutes=10)


BLOOD_TYPES = ("O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-")
CREDIT_SCORE_RANGE = (150, 950)
MONEY_MAX = Decimal("999999999999")

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOCUMENT_RE = re.compile(r"^[0-9A-Za-z-]{5,20}$")
_PHONE_RE = re.compile(r"^\+?[0-9 ]{7,20}$")


# --------------------------------------------------------------------------
# Tipos
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    otp_enabled: bool


@dataclass(frozen=True, slots=True)
class EnrollmentTicket:
    user_id: int
    username: str
    secret: str
    uri: str
    expires_at: dt.datetime
    attempts_left: int


class EnrollStatus(StrEnum):
    ACTIVATED = "activated"
    INVALID = "invalid"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    NOT_PENDING = "not_pending"


@dataclass(frozen=True, slots=True)
class EnrollResult:
    status: EnrollStatus
    attempts_left: int = 0


class RegistrationError(Exception):
    """Errores de validación por campo, con mensajes aptos para la UI."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("registro inválido")
        self.errors = errors


@dataclass(slots=True)
class RegistrationData:
    username: str
    email: str
    password: str
    password_confirm: str
    full_name: str
    document_id: str
    birth_date: dt.date | None
    phone: str
    city: str
    blood_type: str
    allergies: str
    chronic_condition: str
    credit_score: int | None
    monthly_income: Any
    outstanding_debt: Any


# --------------------------------------------------------------------------
# Validación en el servidor
# --------------------------------------------------------------------------


def normalize_username(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw or "").strip().lower()


def normalize_email(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw or "").strip().lower()


def _clean_text(raw: str | None) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    return " ".join(text.split())


def _has_control(text: str) -> bool:
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in text)


def _is_name(text: str) -> bool:
    return all(ch.isalpha() or ch in " '-." for ch in text) and any(ch.isalpha() for ch in text)


def _money(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _years_before(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 de febrero
        return day.replace(year=day.year - years, day=28)


def validate_registration(data: RegistrationData, *, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}

    username = normalize_username(data.username)
    if not _USERNAME_RE.fullmatch(username):
        errors["username"] = "De 3 a 32 caracteres: letras, números, punto, guion o guion bajo."
    clean["username"] = username

    email = normalize_email(data.email)
    local = email.split("@")[0]
    if len(email) > 254 or len(local) > 64 or not _EMAIL_RE.fullmatch(email):
        errors["email"] = "Escribe un correo válido."
    clean["email"] = email

    try:
        clean["password"] = check_policy(data.password or "", username=username, email=email)
    except PasswordPolicyError as exc:
        errors["password"] = str(exc)
    if (data.password or "") != (data.password_confirm or ""):
        errors["password_confirm"] = "Las contraseñas no coinciden."

    full_name = _clean_text(data.full_name)
    if not (3 <= len(full_name) <= 120) or not _is_name(full_name):
        errors["full_name"] = "Escribe un nombre de 3 a 120 letras."
    clean["full_name"] = full_name

    document_id = _clean_text(data.document_id).replace(" ", "")
    if not _DOCUMENT_RE.fullmatch(document_id):
        errors["document_id"] = "De 5 a 20 caracteres: números, letras o guion."
    clean["document_id"] = document_id

    birth = data.birth_date
    adult_limit = _years_before(today, 18)
    if not isinstance(birth, dt.date) or birth < dt.date(1900, 1, 1) or birth > adult_limit:
        errors["birth_date"] = "Debe ser una fecha válida de una persona mayor de edad."
    clean["birth_date"] = birth

    phone = _clean_text(data.phone)
    digits = sum(ch.isdigit() for ch in phone)
    if not _PHONE_RE.fullmatch(phone) or not (7 <= digits <= 15):
        errors["phone"] = "De 7 a 15 dígitos; puede empezar con +."
    clean["phone"] = phone

    city = _clean_text(data.city)
    if not (2 <= len(city) <= 80) or not _is_name(city):
        errors["city"] = "Escribe una ciudad válida."
    clean["city"] = city

    if data.blood_type not in BLOOD_TYPES:
        errors["blood_type"] = "Elige un tipo de sangre."
    clean["blood_type"] = data.blood_type

    for field in ("allergies", "chronic_condition"):
        text = _clean_text(getattr(data, field))
        if len(text) > 200 or _has_control(text):
            errors[field] = "Máximo 200 caracteres."
        clean[field] = text

    score = data.credit_score
    lo, hi = CREDIT_SCORE_RANGE
    if not isinstance(score, int) or isinstance(score, bool) or not (lo <= score <= hi):
        errors["credit_score"] = f"Entre {lo} y {hi}."
    clean["credit_score"] = score

    for field in ("monthly_income", "outstanding_debt"):
        value = _money(getattr(data, field))
        if value is None or value < 0 or value > MONEY_MAX:
            errors[field] = "Escribe un valor entre 0 y 999.999.999.999."
        clean[field] = value

    if errors:
        raise RegistrationError(errors)
    return clean


ACCOUNT_FIELDS = ("username", "email", "password", "password_confirm")


def validate_account(username: str, email: str, password: str, password_confirm: str) -> dict[str, str]:
    """Errores de los campos de la cuenta (paso 1 del registro), con las mismas reglas.

    No consulta la base: los duplicados se detectan al crear la cuenta, con las
    restricciones UNIQUE de PostgreSQL.
    """
    data = RegistrationData(
        username=username, email=email, password=password, password_confirm=password_confirm,
        full_name="", document_id="", birth_date=None, phone="", city="", blood_type="",
        allergies="", chronic_condition="", credit_score=None, monthly_income=None, outstanding_debt=None,
    )
    try:
        validate_registration(data)
    except RegistrationError as exc:
        return {k: v for k, v in exc.errors.items() if k in ACCOUNT_FIELDS}
    return {}


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------

_DUPLICATE_MESSAGES = {
    "app_user_username_key": ("username", "Ese nombre de usuario no está disponible."),
    "app_user_email_key": ("email", "Ese correo no se puede usar para una cuenta nueva."),
}


def register(data: RegistrationData) -> EnrollmentTicket:
    """Crea la cuenta y su perfil, y deja un enrolamiento TOTP pendiente."""
    clean = validate_registration(data)
    password_hash = hash_password(clean["password"])
    settings = get_settings()
    secret = otp.new_secret()
    try:
        with db.connection() as conn, conn.transaction():
            user_id = conn.execute(
                "INSERT INTO today.app_user (username, email, password_hash)"
                " VALUES (%s, %s, %s) RETURNING id",
                (clean["username"], clean["email"], password_hash),
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO today.user_profile (
                    user_id, full_name, document_id, birth_date, phone, city,
                    blood_type, allergies, chronic_condition,
                    credit_score, monthly_income, outstanding_debt
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id, clean["full_name"], clean["document_id"], clean["birth_date"],
                    clean["phone"], clean["city"], clean["blood_type"], clean["allergies"],
                    clean["chronic_condition"], clean["credit_score"],
                    clean["monthly_income"], clean["outstanding_debt"],
                ),
            )
            expires_at = _store_pending_secret(conn, user_id, secret, settings.otp_key)
    except pg_errors.UniqueViolation as exc:
        field, message = _DUPLICATE_MESSAGES.get(
            exc.diag.constraint_name or "", ("username", "La cuenta no se pudo crear.")
        )
        log.info("event=register_duplicate field=%s", field)
        raise RegistrationError({field: message}) from None
    except pg_errors.CheckViolation:
        log.warning("event=register_check_violation")
        raise RegistrationError({"form": "Revisa los datos del formulario."}) from None

    log.info("event=register_ok user_id=%s", user_id)
    return EnrollmentTicket(
        user_id=user_id,
        username=clean["username"],
        secret=secret,
        uri=otp.provisioning_uri(secret, clean["username"], settings.otp_issuer),
        expires_at=expires_at,
        attempts_left=ENROLL_MAX_ATTEMPTS,
    )


def _store_pending_secret(conn: psycopg.Connection, user_id: int, secret: str, key: bytes) -> dt.datetime:
    row = conn.execute(
        """
        UPDATE today.app_user
           SET otp_pending_secret_enc = %s,
               otp_pending_attempts = 0,
               otp_pending_expires_at = now() + %s
         WHERE id = %s
        RETURNING otp_pending_expires_at
        """,
        (otp.encrypt_secret(key, secret, user_id), ENROLL_TTL, user_id),
    ).fetchone()
    return row["otp_pending_expires_at"]


_CLEAR_PENDING = """
    UPDATE today.app_user
       SET otp_pending_secret_enc = NULL,
           otp_pending_attempts = 0,
           otp_pending_expires_at = NULL
     WHERE id = %s
"""


# --------------------------------------------------------------------------
# Intentos fallidos (persistentes por cuenta)
# --------------------------------------------------------------------------

_SELECT_FOR_AUTH = """
    SELECT id, username, password_hash, otp_enabled, otp_secret_enc, otp_last_step,
           failed_attempts,
           (locked_until IS NOT NULL AND locked_until > now()) AS is_locked
      FROM today.app_user
     WHERE username = %s
       FOR UPDATE
"""


def _register_failure(conn: psycopg.Connection, user_id: int, reason: str) -> None:
    row = conn.execute(
        """
        WITH cur AS (
            SELECT CASE WHEN locked_until IS NOT NULL AND locked_until <= now()
                        THEN 1 ELSE failed_attempts + 1 END AS attempts
              FROM today.app_user WHERE id = %(id)s
        )
        UPDATE today.app_user u
           SET failed_attempts = cur.attempts,
               locked_until = CASE WHEN cur.attempts >= %(max)s THEN now() + %(lock)s
                                   WHEN u.locked_until <= now() THEN NULL
                                   ELSE u.locked_until END
          FROM cur
         WHERE u.id = %(id)s
        RETURNING u.failed_attempts, (u.locked_until > now()) AS locked
        """,
        {"id": user_id, "max": MAX_LOGIN_ATTEMPTS, "lock": LOCKOUT},
    ).fetchone()
    log.info(
        "event=auth_failed reason=%s user_id=%s attempts=%s locked=%s",
        reason, user_id, row["failed_attempts"], bool(row["locked"]),
    )


# --------------------------------------------------------------------------
# Inicio de sesión: usuario + contraseña + OTP
# --------------------------------------------------------------------------


def authenticate(username: str, password: str, code: str, *, now: float | None = None) -> User | None:
    """Devuelve el usuario solo si los tres factores son válidos.

    Cualquier fallo devuelve ``None`` sin decir cuál campo falló.
    """
    uname = normalize_username(username)
    code_norm = otp.normalize_code(code)
    settings = get_settings()

    with db.connection() as conn, conn.transaction():
        row = conn.execute(
            _SELECT_FOR_AUTH, (uname,)
        ).fetchone()
        if row is None:
            verify_password(None, password or "")  # mismo coste que una cuenta real
            log.info("event=auth_failed reason=unknown_account")
            return None
        if row["is_locked"]:
            verify_password(None, password or "")
            log.info("event=auth_rejected reason=locked user_id=%s", row["id"])
            return None

        password_ok = verify_password(row["password_hash"], password or "")
        step: int | None = None
        if row["otp_enabled"] and code_norm is not None:
            try:
                secret = otp.decrypt_secret(settings.otp_key, row["otp_secret_enc"], row["id"])
            except otp.SecretDecryptionError:
                log.error("event=otp_secret_undecryptable user_id=%s", row["id"])
                secret = None
            if secret is not None:
                step = otp.matching_step(secret, code_norm, now)

        if not password_ok:
            _register_failure(conn, row["id"], "password")
            return None
        if not row["otp_enabled"]:
            _register_failure(conn, row["id"], "otp_not_enrolled")
            return None
        if step is None:
            _register_failure(conn, row["id"], "otp_invalid")
            return None

        # Consumo atómico del intervalo: solo avanza si es mayor que el último.
        consumed = conn.execute(
            """
            UPDATE today.app_user
               SET otp_last_step = %(step)s,
                   failed_attempts = 0,
                   locked_until = NULL,
                   last_login_at = now()
             WHERE id = %(id)s
               AND (otp_last_step IS NULL OR otp_last_step < %(step)s)
            RETURNING id
            """,
            {"id": row["id"], "step": step},
        ).fetchone()
        if consumed is None:
            _register_failure(conn, row["id"], "otp_reused")
            return None

        if needs_rehash(row["password_hash"]):
            conn.execute(
                "UPDATE today.app_user SET password_hash = %s WHERE id = %s",
                (hash_password(password), row["id"]),
            )

    log.info("event=auth_ok user_id=%s", row["id"])
    return User(id=row["id"], username=row["username"], otp_enabled=True)


# --------------------------------------------------------------------------
# Enrolamiento TOTP
# --------------------------------------------------------------------------


def start_enrollment(username: str, password: str) -> EnrollmentTicket | None:
    """Reinicia el enrolamiento de una cuenta sin segundo factor activo.

    Exige la contraseña y cuenta como intento de inicio de sesión. Una cuenta
    con OTP activo no puede volver a enrolarse por esta vía.
    """
    uname = normalize_username(username)
    settings = get_settings()
    with db.connection() as conn, conn.transaction():
        row = conn.execute(
            _SELECT_FOR_AUTH, (uname,)
        ).fetchone()
        if row is None or row["is_locked"]:
            verify_password(None, password or "")
            log.info("event=enroll_start_failed reason=%s", "locked" if row else "unknown_account")
            return None
        if not verify_password(row["password_hash"], password or ""):
            _register_failure(conn, row["id"], "enroll_password")
            return None
        if row["otp_enabled"]:
            log.info("event=enroll_start_rejected reason=already_enabled user_id=%s", row["id"])
            return None
        conn.execute(
            "UPDATE today.app_user SET failed_attempts = 0, locked_until = NULL WHERE id = %s",
            (row["id"],),
        )
        secret = otp.new_secret()
        expires_at = _store_pending_secret(conn, row["id"], secret, settings.otp_key)

    log.info("event=enroll_started user_id=%s", row["id"])
    return EnrollmentTicket(
        user_id=row["id"],
        username=row["username"],
        secret=secret,
        uri=otp.provisioning_uri(secret, row["username"], settings.otp_issuer),
        expires_at=expires_at,
        attempts_left=ENROLL_MAX_ATTEMPTS,
    )


def get_pending_enrollment(user_id: int) -> EnrollmentTicket | None:
    """Datos del enrolamiento pendiente (vigente) de la cuenta indicada."""
    settings = get_settings()
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, otp_enabled, otp_pending_secret_enc,
                   otp_pending_attempts, otp_pending_expires_at,
                   (otp_pending_expires_at > now()) AS active
              FROM today.app_user WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
    if not row or row["otp_enabled"] or row["otp_pending_secret_enc"] is None or not row["active"]:
        return None
    left = ENROLL_MAX_ATTEMPTS - row["otp_pending_attempts"]
    if left <= 0:
        return None
    try:
        secret = otp.decrypt_secret(settings.otp_key, row["otp_pending_secret_enc"], row["id"])
    except otp.SecretDecryptionError:
        log.error("event=otp_pending_undecryptable user_id=%s", row["id"])
        return None
    return EnrollmentTicket(
        user_id=row["id"],
        username=row["username"],
        secret=secret,
        uri=otp.provisioning_uri(secret, row["username"], settings.otp_issuer),
        expires_at=row["otp_pending_expires_at"],
        attempts_left=left,
    )


def confirm_enrollment(user_id: int, code: str, *, now: float | None = None) -> EnrollResult:
    """Activa el segundo factor si ``code`` es válido para la semilla pendiente."""
    settings = get_settings()
    with db.connection() as conn, conn.transaction():
        row = conn.execute(
            """
            SELECT id, otp_enabled, otp_pending_secret_enc, otp_pending_attempts,
                   (otp_pending_expires_at IS NULL OR otp_pending_expires_at <= now()) AS expired
              FROM today.app_user WHERE id = %s FOR UPDATE
            """,
            (user_id,),
        ).fetchone()
        if not row or row["otp_enabled"] or row["otp_pending_secret_enc"] is None:
            return EnrollResult(EnrollStatus.NOT_PENDING)
        if row["expired"]:
            conn.execute(_CLEAR_PENDING, (user_id,))
            log.info("event=enroll_expired user_id=%s", user_id)
            return EnrollResult(EnrollStatus.EXPIRED)
        if row["otp_pending_attempts"] >= ENROLL_MAX_ATTEMPTS:
            conn.execute(_CLEAR_PENDING, (user_id,))
            return EnrollResult(EnrollStatus.EXHAUSTED)

        try:
            secret = otp.decrypt_secret(settings.otp_key, row["otp_pending_secret_enc"], user_id)
        except otp.SecretDecryptionError:
            log.error("event=otp_pending_undecryptable user_id=%s", user_id)
            conn.execute(_CLEAR_PENDING, (user_id,))
            return EnrollResult(EnrollStatus.EXPIRED)

        step = otp.matching_step(secret, code, now)
        if step is None:
            attempts = row["otp_pending_attempts"] + 1
            if attempts >= ENROLL_MAX_ATTEMPTS:
                conn.execute(_CLEAR_PENDING, (user_id,))
                log.info("event=enroll_exhausted user_id=%s", user_id)
                return EnrollResult(EnrollStatus.EXHAUSTED)
            conn.execute(
                "UPDATE today.app_user SET otp_pending_attempts = %s WHERE id = %s",
                (attempts, user_id),
            )
            log.info("event=enroll_code_invalid user_id=%s attempts=%s", user_id, attempts)
            return EnrollResult(EnrollStatus.INVALID, ENROLL_MAX_ATTEMPTS - attempts)

        conn.execute(
            """
            UPDATE today.app_user
               SET otp_secret_enc = %s,
                   otp_enabled = true,
                   otp_last_step = %s,
                   otp_pending_secret_enc = NULL,
                   otp_pending_attempts = 0,
                   otp_pending_expires_at = NULL
             WHERE id = %s AND NOT otp_enabled
            """,
            (otp.encrypt_secret(settings.otp_key, secret, user_id), step, user_id),
        )
    log.info("event=enroll_activated user_id=%s", user_id)
    return EnrollResult(EnrollStatus.ACTIVATED)


def cancel_enrollment(user_id: int) -> None:
    with db.connection() as conn, conn.transaction():
        conn.execute(_CLEAR_PENDING + " AND NOT otp_enabled", (user_id,))


# --------------------------------------------------------------------------
# Consultas para acciones protegidas
# --------------------------------------------------------------------------


def get_user(user_id: int) -> User | None:
    """Estado actual de la cuenta leído de la base."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, username, otp_enabled FROM today.app_user WHERE id = %s",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return User(id=row["id"], username=row["username"], otp_enabled=row["otp_enabled"])


def get_account(user_id: int) -> dict[str, Any] | None:
    """Datos de la propia cuenta para el panel (sin hash ni semillas)."""
    with db.connection() as conn:
        return conn.execute(
            """
            SELECT u.username, u.email, u.created_at, u.last_login_at, u.otp_enabled,
                   p.full_name, p.document_id, p.birth_date, p.phone, p.city,
                   p.blood_type, p.allergies, p.chronic_condition,
                   p.credit_score, p.monthly_income, p.outstanding_debt
              FROM today.app_user u
              LEFT JOIN today.user_profile p ON p.user_id = u.id
             WHERE u.id = %s
            """,
            (user_id,),
        ).fetchone()
