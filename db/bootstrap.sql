-- Preparación única de roles y base de datos (la ejecuta el DBA, no la app).
--
-- En la VM de PostgreSQL, como superusuario:
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -f bootstrap.sql
--   sudo -u postgres psql -c '\password today_owner'
--   sudo -u postgres psql -c '\password today_app'
--
-- today_owner: dueño de la base y del esquema `today`. Solo ejecuta
--              migraciones y tareas de administración (today-admin).
-- today_app:   rol con el que se conecta Streamlit. Recibe permisos mínimos
--              desde las migraciones; no puede crear ni borrar objetos.
--
-- Si ya existen una base y un rol en la VM, adapta los nombres (y define
-- TODAY_APP_ROLE) en vez de crear otros.

SELECT 'CREATE ROLE today_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'today_owner')\gexec

SELECT 'CREATE ROLE today_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 20'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'today_app')\gexec

SELECT 'CREATE DATABASE today OWNER today_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'today')\gexec

REVOKE ALL ON DATABASE today FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE today TO today_owner;
GRANT CONNECT ON DATABASE today TO today_app;

\connect today
REVOKE ALL ON SCHEMA public FROM PUBLIC;
