# today

Aplicación Streamlit de la entrega de Ciberseguridad: registro con datos de demostración, inicio de sesión con **usuario + contraseña + código TOTP**, y descarga CSV de todos los usuarios para cualquier cuenta con sesión iniciada (el enunciado no pide roles). Usa PostgreSQL y se ejecuta con `uv`.

> Los campos de datos personales, salud y crédito son **académicos**. Usa solo datos ficticios (`today-admin seed-demo` los genera).

Documentación completa (funcionamiento, arquitectura, base de datos, seguridad, ejecución y despliegue): [`docs/DOCUMENTACION.md`](docs/DOCUMENTACION.md).

## Contenido

| Ruta | Qué hay |
| --- | --- |
| `src/web_app/main.py` | Entrada de Streamlit, navegación propia y cabecera |
| `src/web_app/all_pages/` | Acceso (login en dos pasos / registro en tres / autenticador); con sesión: Resumen (descarga CSV), Datos personales, Salud, Crédito, Seguridad y Equipos A·B·Chat |
| `src/web_app/panel.py` | Vistas de las secciones de la cuenta |
| `src/web_app/services/accounts.py` | Registro, enrolamiento TOTP, inicio de sesión, bloqueo |
| `src/web_app/services/export.py` | CSV con columnas explícitas y celdas neutralizadas |
| `src/web_app/security/` | Política de contraseñas + Argon2id; TOTP + cifrado AES-256-GCM |
| `src/web_app/migrations/` | Migraciones SQL versionadas |
| `src/web_app/migrate.py`, `admin.py` | CLI `today-migrate` y `today-admin` |
| `src/web_app/ui/` | Tema (CSS sin React ni JavaScript), favicon |
| `db/bootstrap.sql` | Creación única de roles y base (la ejecuta el DBA) |
| `deploy/` | Unidad systemd propuesta y fragmento opcional de Nginx |
| `docs/DOCUMENTACION.md` | Documentación completa de la app |
| `tests/` | Pruebas con pytest y PostgreSQL real |

## Configuración

Variables de entorno (ejemplo con valores ficticios en [`.env.example`](.env.example)):

| Variable | Uso |
| --- | --- |
| `TODAY_DATABASE_URL` | Conexión del **rol de la aplicación** (`today_app`) |
| `TODAY_OTP_ENCRYPTION_KEY` | Clave AES-256 en base64 (32 bytes) para cifrar las semillas TOTP. Vive fuera de PostgreSQL |
| `TODAY_APP_ROLE` | Rol al que las migraciones dan permisos (por defecto `today_app`) |
| `TODAY_OTP_ISSUER` | Nombre que muestra la app autenticadora (por defecto `today`) |
| `TODAY_TIMEZONE` | Zona horaria para mostrar fechas (por defecto `America/Bogota`) |
| `TODAY_MIGRATOR_DATABASE_URL` | Solo para `today-migrate` y `today-admin unlock`: rol **dueño** del esquema |

Generar la clave de OTP:

```bash
uv run python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Si se pierde esta clave, las semillas guardadas no se pueden descifrar y cada usuario tendría que volver a enrolar su OTP. Guárdala en el gestor de secretos del equipo.

`.gitignore` excluye `.env`, `*.env`, volcados (`*.dump`, `*.pgdump`, `*.backup`, `dumps/`, `backups/`), exportaciones (`*.csv`, `*.xlsx`, `exports/`) y `.streamlit/secrets.toml`.

## Base de datos

### Roles (una sola vez, en la VM de PostgreSQL)

| Rol | Para qué | Permisos |
| --- | --- | --- |
| `today_owner` | Migraciones y administración | Dueño de la base `today` y del esquema `today` |
| `today_app` | La aplicación Streamlit | `SELECT` en cuentas y perfiles; `INSERT` de usuario/correo/hash y perfil; `UPDATE` solo de columnas de login y OTP. Sin `DELETE`, sin DDL, sin cambiar usuario ni correo |

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1 -f bootstrap.sql
sudo -u postgres psql -c '\password today_owner'
sudo -u postgres psql -c '\password today_app'
```

Y en `pg_hba.conf`, permite solo la IP privada de la VM web para la base `today` con `scram-sha-256`.

### Migraciones

Cada archivo `src/web_app/migrations/NNNN_nombre.sql` se aplica una vez, en su propia transacción, y queda registrado en `today.schema_migrations` con su suma SHA-256. Si un archivo ya aplicado cambia, el comando se detiene. Las migraciones conservan las filas existentes:

- `0001` crea las tablas, las restricciones y los permisos.
- `0002` quita la columna `role`. El enunciado no pide roles de aplicación, así que cualquier cuenta autenticada puede descargar el CSV. Probada sobre una base con 19 cuentas: quedan las 19 y sus perfiles.

**Quién la ejecuta:** el rol `today_owner`, nunca `today_app`. En el servidor no se guarda su contraseña: se pide al migrar.

```bash
# En la VM web, como ubuntu, desde /home/ubuntu/Developer/today
read -rsp "Clave de today_owner: " PGPASSWORD; echo; export PGPASSWORD
export TODAY_MIGRATOR_DATABASE_URL='postgresql://today_owner@IP_PRIVADA_PG:5432/today'
uv run --no-sync today-migrate status   # qué hay pendiente
uv run --no-sync today-migrate          # aplica lo pendiente
uv run --no-sync today-migrate status   # todas deben decir "aplicada"
unset PGPASSWORD TODAY_MIGRATOR_DATABASE_URL
```

Verificación con el rol de la aplicación:

```bash
uv run --no-sync --env-file /etc/today/today.env today-admin check
# configuración: ok · rol de conexión: today_app
# permisos mínimos: ok (cambia usuarios=False, borra=False, vacía=False, crea objetos=False)
```

### Desbloquear una cuenta

La aplicación no tiene roles: todas las cuentas tienen los mismos permisos. Para quitar un bloqueo por intentos fallidos antes de que pasen los 15 minutos:

```bash
uv run --no-sync today-admin unlock <usuario>   # usa TODAY_MIGRATOR_DATABASE_URL
```

## Ejecutar en local

```bash
uv sync                                    # Python 3.14 según .python-version
cp .env.example .env                       # y rellena valores locales
uv run --env-file .env today-migrate
uv run --env-file .env today-admin seed-demo --count 12   # cuentas ficticias para el CSV
uv run --env-file .env streamlit run src/web_app/main.py  # http://127.0.0.1:8501
```

Para ver trazas de error en el navegador mientras desarrollas: `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=full`. Streamlit no recarga los módulos de `web_app` al editarlos: reinicia el servidor tras cambiar algo fuera de `all_pages/`.

PostgreSQL de desarrollo con Docker:

```bash
docker run -d --name today-pg-dev -e POSTGRES_PASSWORD=solo-local -p 127.0.0.1:55432:5432 postgres:18-alpine
docker exec -i today-pg-dev psql -U postgres -v ON_ERROR_STOP=1 < db/bootstrap.sql
docker exec today-pg-dev psql -U postgres -c "ALTER ROLE today_owner PASSWORD 'local-owner'" -c "ALTER ROLE today_app PASSWORD 'local-app'"
```

## Controles de seguridad

**Política de contraseñas** (validada en el servidor, `security/passwords.py`):

- Normalización Unicode NFKC antes de validar y de calcular el hash.
- Entre 12 y 128 caracteres. Al menos una letra y al menos un número o símbolo. Al menos 6 caracteres distintos.
- No puede contener el usuario ni la parte local del correo, ni ser una contraseña común o una palabra común con números alrededor (`Password2025!`, `Contraseña123`). Sin caracteres de control.

**Hash:** Argon2id con `argon2-cffi`: t=3, m=64 MiB, p=4, sal aleatoria de 16 bytes por contraseña (perfil de RFC 9106). Si los parámetros cambian, el hash se actualiza en el siguiente login.

**Registro:** validación de cada campo en el servidor, consultas parametrizadas y restricciones `UNIQUE`/`CHECK` en PostgreSQL. El usuario y el correo se guardan en minúsculas, así que `Ana` y `ana` cuentan como duplicado. Un duplicado devuelve un mensaje por campo y no deja filas a medias.

**TOTP** (`pyotp`, 6 dígitos, 30 s):

- Una semilla de 160 bits por usuario, cifrada con AES-256-GCM. El id del usuario va como dato asociado, así que una semilla copiada a otra fila no se puede descifrar.
- El QR se genera en memoria y se envía como imagen embebida, sin URL de descarga. Solo lo ve la sesión que acaba de registrar la cuenta o que confirmó la contraseña. El enrolamiento vence a los 10 minutos y permite 5 intentos; después hay que pedir otro QR.
- Los códigos son texto de exactamente 6 dígitos ASCII, así que se conservan los ceros iniciales.
- Se acepta el intervalo actual ±1. El intervalo aceptado se guarda en `otp_last_step` con un `UPDATE ... WHERE otp_last_step < paso` dentro de una transacción que bloquea la fila. Un código no se puede reutilizar, ni siquiera con dos intentos simultáneos.

**Inicio de sesión:** en dos pantallas, como en una app real: primero usuario y contraseña, después el código. El paso 1 no consulta la base ni dice si la contraseña es correcta; los tres datos se verifican juntos al enviar el código, así que el paso 1 no sirve para probar contraseñas. Entre los dos pasos, usuario y contraseña quedan solo en la sesión del servidor durante un máximo de 5 minutos y se borran con cualquier resultado. Cualquier fallo responde «No pudimos verificar tus datos» sin decir cuál falló, y una cuenta inexistente también calcula un hash para no revelarse por el tiempo de respuesta. 5 fallos bloquean la cuenta 15 minutos. El contador vive en PostgreSQL, sobrevive a reinicios y no pierde intentos aunque lleguen en paralelo.

**Navegación:** sin sesión, la app solo registra la página de acceso; las secciones de la cuenta y las páginas de equipos no existen para ese navegador. Con sesión, la barra lateral lleva a Resumen (página por defecto), Datos personales, Salud, Crédito, Seguridad y los equipos.

**Registro:** en tres pasos: 1) cuenta, 2) datos de demostración (con aviso de que son ficticios), 3) autenticador. El paso 1 se valida con las mismas reglas del servidor sin tocar la base; la cuenta se crea al terminar el paso 2 y, si el usuario o el correo ya existen (restricción `UNIQUE` de PostgreSQL), se vuelve al paso 1 con el mensaje en su campo. Entre el paso 1 y el 2 la contraseña queda solo en la sesión del servidor, como mucho 15 minutos; al volver atrás hay que escribirla de nuevo.

**Sesión:** `st.session_state` (en el servidor) guarda solo el id de la cuenta. En cada página se relee la cuenta y el estado del OTP desde la base. La sesión caduca tras 30 minutos de inactividad o 8 horas en total. Al iniciar sesión el estado se reinicia y «Cerrar sesión» lo borra entero. Las contraseñas y los códigos se vacían de los widgets tras cada intento.

**CSV:** el botón **Descargar CSV** está en el resumen de cualquier cuenta con sesión; sin sesión no existe. Al hacer clic, el generador vuelve a comprobar en la base que la cuenta existe y tiene el OTP activo antes de consultar los datos. La exportación usa una lista explícita de columnas, sin hashes, semillas, contadores ni tokens. Las celdas que empiezan por `= + - @`, tabulación o retorno se prefijan con `'`.

**Logs:** solo llevan el evento y el id interno (`event=auth_failed reason=otp_invalid user_id=4`). Nunca contraseñas, códigos, semillas, correos, nombres de usuario ni datos de formularios. En el servidor van a journald.

**Interfaz:** tema propio en `.streamlit/config.toml` más `ui/style.css`, inyectado con `st.html` (sin componentes React ni JavaScript): tablero blanco sobre fondo nocturno, riel lateral azul noche, baldosas pastel e iconos de Material Symbols (la fuente que ya trae Streamlit). En el acceso, la columna derecha muestra los pasos del recorrido y un carrusel con los integrantes del equipo (`src/web_app/team.py`). La barra superior, el menú y la navegación de Streamlit están ocultos. Las animaciones respetan `prefers-reduced-motion`.

## Pruebas

```bash
# Sin base de datos: solo las unitarias (las de PostgreSQL se omiten)
uv run pytest

# Completas, con un PostgreSQL de DESARROLLO (crea y borra una base y roles temporales)
# (usa la contraseña de POSTGRES_PASSWORD con la que creaste el contenedor)
TODAY_TEST_ADMIN_URL='postgresql://postgres:solo-local@127.0.0.1:55432/postgres' uv run pytest
```

Cubren: registro y duplicados (usuario y correo, sin importar mayúsculas), validación en el servidor, las 8 combinaciones de usuario/contraseña/OTP, OTP con cero inicial, código vencido, código reutilizado (también en paralelo), límite de intentos persistente (también en paralelo), límite y vencimiento del enrolamiento, cifrado de semillas, permisos mínimos del rol de la app, migraciones idempotentes y detección de cambios, contenido exacto del CSV y neutralización de fórmulas, denegación del CSV a cuentas inexistentes o sin OTP (también si la cuenta desaparece después de pintar el botón), columna `role` eliminada, logs sin secretos y pruebas de la UI con `streamlit.testing`: login en dos pasos (el paso 1 no cuenta intentos ni revela la contraseña, el paso 2 vence a los 5 minutos), cierre de sesión, páginas inexistentes sin sesión, registro en tres pasos (el paso 1 no crea nada en la base, volver atrás conserva los datos y pide la contraseña, usuario duplicado devuelve al paso 1), QR solo en su sesión, configuración del autenticador desde el paso 2, descarga visible para cualquier cuenta con sesión y solo en el resumen.

Último resultado local (PostgreSQL 18.6, Python 3.14.7, Streamlit 1.66.1): **123 passed**; sin base de datos, 42 passed y 81 skipped.

## Despliegue (VM web)

Esquema: Ubuntu, usuario `ubuntu`, clon en `/home/ubuntu/Developer/today`, unidad `cyber.service`, Nginx con HTTPS → Streamlit en `127.0.0.1:8501`, PostgreSQL en otra VM privada.

1. **Código y dependencias**

   ```bash
   cd /home/ubuntu/Developer/today
   git pull --ff-only
   uv sync --frozen --no-dev
   ```

2. **Secretos** (una vez)

   ```bash
   sudo install -d -m 0750 -o root -g ubuntu /etc/today
   sudo install -m 0640 -o root -g ubuntu .env.example /etc/today/today.env
   sudoedit /etc/today/today.env     # TODAY_DATABASE_URL, TODAY_OTP_ENCRYPTION_KEY (nueva), TODAY_APP_ROLE
   ```

3. **Base de datos**: `bootstrap.sql` (si aún no existen los roles) y `today-migrate`, como se describe arriba.

4. **Servicio**: compara `deploy/cyber.service` con la unidad actual (`systemctl cat cyber.service`). La propuesta añade `EnvironmentFile` (los secretos), fija `WorkingDirectory` en el clon (Streamlit lee `.streamlit/config.toml` desde ahí) y arranca con `uv run --no-sync`, de modo que no instala nada al iniciar. También añade endurecimiento básico.

   ```bash
   sudo cp deploy/cyber.service /etc/systemd/system/cyber.service   # tras revisarla
   sudo systemctl daemon-reload
   sudo systemctl restart cyber.service
   ```

5. **Opcional:** `deploy/nginx-sin-marca-streamlit.conf` evita que el título y el favicon de Streamlit se vean un instante antes de que cargue la app.

### Prueba después del despliegue

```bash
systemctl status cyber.service --no-pager
curl -fsS http://127.0.0.1:8501/_stcore/health          # → ok
curl -fsSI https://TU_DOMINIO/ | head -1                  # → HTTP/2 200
uv run --no-sync --env-file /etc/today/today.env today-admin check
journalctl -u cyber.service -n 30 --no-pager
```

En el navegador, con datos ficticios:

1. La URL abre directamente en **Inicia sesión**. Pulsa **Crea una**, escribe usuario, correo y contraseña y pulsa **Siguiente**. En el paso 2 pulsa **Llenar con datos ficticios** y **Crear cuenta**. Escanea el QR y activa el código.
2. Inicia sesión: usuario y contraseña, **Continuar**, y luego el código. Deben salir el resumen («Hola, …») y `event=auth_ok` en journald.
3. Intenta reutilizar el mismo código. Debe fallar con un mensaje genérico.
4. Pulsa **Descargar CSV** en el resumen. Revisa que no haya hashes ni semillas y que las celdas con `=`/`+` empiecen por `'`.
5. Sin sesión (otra ventana privada), la URL solo muestra **Inicia sesión** y no hay descarga.
6. **Cerrar sesión** (último icono del riel). Debe volver a **Inicia sesión**.
