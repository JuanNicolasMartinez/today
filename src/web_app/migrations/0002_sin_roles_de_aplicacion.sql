-- 0002 · Sin roles de aplicación.
--
-- El enunciado del proyecto no pide roles: cualquier cuenta con sesión
-- autenticada (usuario + contraseña + OTP) puede descargar el CSV. Se elimina
-- la columna `role` (su CHECK app_user_role_valid cae con ella). Las demás
-- columnas, los permisos y todas las filas se conservan.
--
-- Lo ejecuta el rol dueño del esquema (today_owner) con `uv run today-migrate`.

ALTER TABLE today.app_user DROP COLUMN IF EXISTS role;
