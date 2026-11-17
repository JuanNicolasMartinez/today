-- 0001 · Cuentas, segundo factor TOTP y perfil de demostración.
--
-- Lo ejecuta el rol dueño del esquema (today_owner) con `uv run today-migrate`.
-- {{app_role}} lo sustituye el ejecutor por el rol de la aplicación, ya citado
-- como identificador SQL. Solo crea objetos nuevos: no modifica filas.

CREATE TABLE today.app_user (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username                text        NOT NULL,
    email                   text        NOT NULL,
    password_hash           text        NOT NULL,
    role                    text        NOT NULL DEFAULT 'member',
    created_at              timestamptz NOT NULL DEFAULT now(),
    last_login_at           timestamptz,

    -- Límite persistente de intentos de inicio de sesión.
    failed_attempts         integer     NOT NULL DEFAULT 0,
    locked_until            timestamptz,

    -- Segundo factor activo. La semilla está cifrada con AES-256-GCM; la clave
    -- vive fuera de PostgreSQL (TODAY_OTP_ENCRYPTION_KEY).
    otp_enabled             boolean     NOT NULL DEFAULT false,
    otp_secret_enc          bytea,
    -- Último intervalo TOTP aceptado. Un código solo vale si su intervalo es
    -- mayor: así no se puede reutilizar.
    otp_last_step           bigint,

    -- Enrolamiento pendiente: semilla cifrada, intentos y vencimiento.
    otp_pending_secret_enc  bytea,
    otp_pending_attempts    integer     NOT NULL DEFAULT 0,
    otp_pending_expires_at  timestamptz,

    CONSTRAINT app_user_username_key UNIQUE (username),
    CONSTRAINT app_user_email_key UNIQUE (email),
    CONSTRAINT app_user_username_format
        CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,31}$'),
    CONSTRAINT app_user_email_format
        CHECK (char_length(email) <= 254
               AND email = lower(email)
               AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
    CONSTRAINT app_user_role_valid CHECK (role IN ('member', 'auditor')),
    CONSTRAINT app_user_failed_attempts_valid CHECK (failed_attempts >= 0),
    CONSTRAINT app_user_pending_attempts_valid CHECK (otp_pending_attempts >= 0),
    CONSTRAINT app_user_otp_enabled_has_secret
        CHECK (NOT otp_enabled OR otp_secret_enc IS NOT NULL)
);

COMMENT ON TABLE today.app_user IS 'Cuentas. Sin datos de demostración.';

-- Campos académicos de demostración: datos personales, salud y crédito.
CREATE TABLE today.user_profile (
    user_id            bigint      PRIMARY KEY
                                   REFERENCES today.app_user (id) ON DELETE CASCADE,
    full_name          text        NOT NULL CHECK (char_length(full_name) BETWEEN 3 AND 120),
    document_id        text        NOT NULL CHECK (document_id ~ '^[0-9A-Za-z-]{5,20}$'),
    birth_date         date        NOT NULL CHECK (birth_date >= DATE '1900-01-01'),
    phone              text        NOT NULL CHECK (phone ~ '^\+?[0-9 ]{7,20}$'),
    city               text        NOT NULL CHECK (char_length(city) BETWEEN 2 AND 80),
    blood_type         text        NOT NULL
                                   CHECK (blood_type IN ('O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-')),
    allergies          text        NOT NULL DEFAULT '' CHECK (char_length(allergies) <= 200),
    chronic_condition  text        NOT NULL DEFAULT '' CHECK (char_length(chronic_condition) <= 200),
    credit_score       integer     NOT NULL CHECK (credit_score BETWEEN 150 AND 950),
    monthly_income     numeric(14, 2) NOT NULL CHECK (monthly_income BETWEEN 0 AND 999999999999),
    outstanding_debt   numeric(14, 2) NOT NULL CHECK (outstanding_debt BETWEEN 0 AND 999999999999),
    created_at         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE today.user_profile IS 'Datos de demostración (académicos). Solo datos ficticios.';

-- Permisos mínimos del rol de la aplicación -------------------------------
-- Sin DELETE, sin DDL y sin acceso a today.schema_migrations.
-- La columna role no se puede insertar ni actualizar desde la aplicación:
-- se asigna con `uv run today-admin set-role` usando el rol dueño.

GRANT USAGE ON SCHEMA today TO {{app_role}};

GRANT SELECT ON today.app_user TO {{app_role}};
GRANT INSERT (username, email, password_hash) ON today.app_user TO {{app_role}};
GRANT UPDATE (
    password_hash, last_login_at, failed_attempts, locked_until,
    otp_enabled, otp_secret_enc, otp_last_step,
    otp_pending_secret_enc, otp_pending_attempts, otp_pending_expires_at
) ON today.app_user TO {{app_role}};

GRANT SELECT, INSERT ON today.user_profile TO {{app_role}};
