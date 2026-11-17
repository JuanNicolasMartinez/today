# today · Documentación de la aplicación

Aplicación web de la entrega de Ciberseguridad, hecha con Streamlit y PostgreSQL. Permite crear una cuenta con datos de demostración, iniciar sesión con **usuario, contraseña y código TOTP** y descargar en CSV los usuarios registrados.

Equipo: Nicolás Martínez, Laurence Santamaría, María José Barreto, Natali Alba y Daniel Camacho.

> Los datos personales, de salud y de crédito son **académicos**. Escribe solo datos inventados o usa los generadores de datos ficticios de la app.

## Contenido

1. [Qué hace la aplicación](#1-qué-hace-la-aplicación)
2. [Recorridos de uso](#2-recorridos-de-uso)
3. [Cómo está construida](#3-cómo-está-construida)
4. [Base de datos](#4-base-de-datos)
5. [Seguridad](#5-seguridad)
6. [Configuración](#6-configuración)
7. [Cómo correrla en local](#7-cómo-correrla-en-local)
8. [Pruebas](#8-pruebas)
9. [Despliegue en el servidor](#9-despliegue-en-el-servidor)
10. [Operación y solución de problemas](#10-operación-y-solución-de-problemas)
11. [Decisiones y límites conocidos](#11-decisiones-y-límites-conocidos)

---

## 1. Qué hace la aplicación

| Función | Qué ve el usuario |
| --- | --- |
| **Registro** | Tres pasos: cuenta (usuario, correo, contraseña) → datos de demostración (personales, salud, crédito) → autenticador (QR). |
| **Autenticador TOTP** | Un QR y una clave para Google Authenticator, Aegis, 1Password u otra app. Se activa al confirmar un código. |
| **Inicio de sesión** | Dos pantallas: usuario y contraseña, y después el código de seis dígitos. |
| **Panel** | Barra lateral con Resumen, Datos personales, Salud, Crédito y Seguridad. El contenido se muestra en un recuadro gris a la derecha. |
| **Descarga CSV** | En el Resumen, el botón **Descargar CSV** baja todas las cuentas con sus datos de demostración. Está disponible para cualquier cuenta con sesión iniciada. |
| **Equipos A, B y Chat** | Páginas que venían en la plantilla del repositorio. Se conservan y se abren desde la barra lateral. |

Sin sesión, la aplicación solo tiene la página de acceso. El panel, las secciones y las páginas de equipos no existen para ese navegador.

---

## 2. Recorridos de uso

### 2.1 Crear una cuenta

```mermaid
flowchart LR
    A[Inicia sesión] -->|Crea una| B["Paso 1 · Cuenta<br/>usuario, correo, contraseña"]
    B -->|Siguiente: valida reglas<br/>sin tocar la base| C["Paso 2 · Datos de demostración<br/>personales, salud, crédito"]
    C -->|Atrás| B
    C -->|"Crear cuenta: INSERT<br/>(UNIQUE decide duplicados)"| D["Paso 3 · Autenticador<br/>QR + clave"]
    C -.->|usuario o correo ya existe| B
    D -->|código correcto| A
```

1. **Cuenta.** Al pulsar **Siguiente**, el servidor valida usuario, correo y contraseña con las mismas reglas del registro, sin consultar la base. Si hay errores, salen bajo cada campo y la contraseña se borra.
2. **Datos de demostración.** Un aviso indica que son datos de práctica. El botón **Llenar con datos ficticios** completa todo con valores inventados. **Atrás** conserva lo escrito, pero pide de nuevo la contraseña.
3. **Crear cuenta.** Se crean la cuenta y el perfil en una sola transacción. Si el usuario o el correo ya existen, PostgreSQL lo detecta con sus restricciones `UNIQUE` y la app vuelve al paso 1 con el mensaje en ese campo. Si un dato de demostración no es válido (por ejemplo, un puntaje fuera de 150–950), el error sale bajo ese campo.
4. Entre el paso 1 y el 2, la contraseña queda solo en la memoria de la sesión del servidor, como mucho **15 minutos**, y se borra con cualquier resultado.

### 2.2 Configurar el autenticador

- Tras crear la cuenta aparece el QR y una clave en bloques de cuatro, para escribirla a mano si no se puede escanear.
- El QR se genera en memoria y solo se muestra en la sesión de navegador que creó la cuenta.
- El enrolamiento **vence a los 10 minutos** y permite **5 intentos**. Después hay que pedir otro QR.
- Al confirmar un código válido, el segundo factor queda activo y la app vuelve a **Inicia sesión**.
- Si alguien creó la cuenta pero no terminó este paso, puede retomarlo desde la pantalla del código con **¿Aún no configuras el autenticador? → Configúralo**. Eso exige la contraseña correcta y solo funciona mientras el segundo factor no esté activo.

### 2.3 Iniciar sesión

```mermaid
sequenceDiagram
    actor U as Usuario
    participant P as Página de acceso
    participant S as services/accounts.py
    participant DB as PostgreSQL

    U->>P: Paso 1: usuario + contraseña
    Note over P: No consulta la base.<br/>Guarda ambos en la sesión del servidor (máx. 5 min)
    P-->>U: Paso 2: pide el código
    U->>P: Código de 6 dígitos
    P->>S: authenticate(usuario, contraseña, código)
    S->>DB: SELECT … FOR UPDATE (bloquea la fila)
    S->>S: Argon2id + TOTP (ventana ±1)
    S->>DB: UPDATE otp_last_step … WHERE otp_last_step < paso
    alt los tres datos son válidos y el código no se usó
        S-->>P: User
        P-->>U: Panel (Resumen)
    else cualquier fallo
        S->>DB: suma un intento fallido (bloqueo a los 5)
        S-->>P: None
        P-->>U: «No pudimos verificar tus datos…» y vuelve al paso 1
    end
```

- El paso 1 nunca dice si la contraseña es correcta. Los tres datos se verifican juntos al enviar el código, así que ese paso no sirve para probar contraseñas.
- Cualquier fallo muestra el mismo mensaje: «No pudimos verificar tus datos. Revisa usuario, contraseña y código.»
- **5 fallos** bloquean la cuenta **15 minutos**.
- Si pasan más de **5 minutos** entre el paso 1 y el 2, hay que empezar de nuevo.

### 2.4 Panel

| Sección (barra lateral) | Contenido |
| --- | --- |
| **Resumen** (página por defecto) | Saludo, tarjeta con nombre e iniciales, ciudad, tipo de sangre, puntaje, correo, estado del 2FA y el bloque **Descargar usuarios**. |
| **Datos personales** | Nombre, documento (enmascarado: solo los 4 últimos dígitos), nacimiento, teléfono, ciudad, usuario. |
| **Salud** | Tipo de sangre, alergias, condición crónica. |
| **Crédito** | Barra animada con el puntaje (150–950), ingreso mensual y deuda vigente. |
| **Seguridad** | Estado del autenticador, algoritmo de contraseña, política de bloqueo, caducidad de la sesión, último acceso y fecha de creación. |
| **Equipo A / B / Chat** | Páginas del repositorio original. |
| **Cerrar sesión** | Último icono de la barra. |

### 2.5 Descargar usuarios

1. En el Resumen se pulsa **Descargar CSV**.
2. En ese momento, el servidor vuelve a comprobar en la base que la cuenta existe y tiene el segundo factor activo. Solo entonces consulta los datos.
3. El archivo `today_demo_AAAAMMDD_HHMM.csv` (hora UTC) trae una fila por cuenta con estas 15 columnas:

   `usuario`, `correo`, `segundo_factor_activo`, `creado_en`, `nombre_completo_demo`, `documento_demo`, `fecha_nacimiento_demo`, `telefono_demo`, `ciudad_demo`, `tipo_sangre_demo`, `alergias_demo`, `condicion_cronica_demo`, `puntaje_credito_demo`, `ingreso_mensual_demo`, `deuda_vigente_demo`.

   - **No incluye:** hashes, semillas OTP, contadores de intentos, credenciales ni tokens.
   - **Neutralización:** las celdas que empiezan (incluso tras espacios) por `=`, `+`, `-`, `@`, tabulación, retorno o sus variantes de ancho completo se prefijan con `'`, para que una hoja de cálculo no las ejecute como fórmula.
   - **Formato:** UTF-8 con BOM (Excel muestra bien las tildes), todos los campos entre comillas, finales de línea CRLF.

### 2.6 Cerrar sesión y caducidad

- **Cerrar sesión** borra todo el estado de la sesión y vuelve a **Inicia sesión**.
- La sesión caduca tras **30 minutos** sin uso o **8 horas** en total.
- En cada página, la app vuelve a leer la cuenta desde la base. Si la cuenta desaparece o pierde el segundo factor, la sesión se cierra.

---

## 3. Cómo está construida

### 3.1 Vista general

```mermaid
flowchart LR
    B["Navegador"] -- HTTPS --> N["Nginx<br/>VM web (Ubuntu)"]
    N -- "HTTP + WebSocket<br/>127.0.0.1:8501" --> S["Streamlit<br/>cyber.service"]
    E[("/etc/today/today.env<br/>secretos")] -. EnvironmentFile .-> S
    S -- "psycopg · rol today_app<br/>red privada :5432" --> D[("PostgreSQL<br/>VM privada")]
    A["today-migrate / today-admin<br/>rol today_owner"] -. migraciones .-> D
```

Streamlit escucha solo en `127.0.0.1:8501`. Nginx publica la app con HTTPS y PostgreSQL vive en otra VM privada. La app se conecta con un rol de permisos mínimos (`today_app`). Las migraciones usan otro rol, dueño del esquema (`today_owner`).

### 3.2 Tecnologías

| Pieza | Versión probada | Para qué |
| --- | --- | --- |
| Python | 3.14 (`.python-version`) | Lenguaje |
| uv | 0.12 | Entorno, dependencias (`pyproject.toml` + `uv.lock`) y ejecución |
| Streamlit | 1.66.1 | Interfaz web |
| PostgreSQL | 18.6 | Base de datos |
| psycopg + psycopg_pool | 3.3.9 | Conexión y pool de conexiones |
| argon2-cffi | 25.1.0 | Hash Argon2id de contraseñas |
| pyotp | 2.x | Códigos TOTP (RFC 6238) |
| cryptography | 50.0.2 | AES-256-GCM para cifrar semillas |
| qrcode[pil] | 8.2 | QR de enrolamiento |
| pytest | 9.2 | Pruebas |

### 3.3 Estructura del código

```text
today/
├── pyproject.toml, uv.lock, .python-version   dependencias y versión de Python
├── .env.example                               variables de entorno con valores ficticios
├── .streamlit/config.toml                     servidor (127.0.0.1:8501, XSRF) y tema
├── db/bootstrap.sql                           roles y base (una sola vez, la ejecuta el DBA)
├── deploy/
│   ├── cyber.service                          unidad systemd propuesta
│   └── nginx-sin-marca-streamlit.conf         fragmento opcional de Nginx
├── docs/DOCUMENTACION.md                      este documento
├── src/web_app/
│   ├── main.py                     entrada: página, navegación, barra lateral, recuadro gris
│   ├── all_pages/
│   │   ├── 2_auth_page.py          acceso: login (2 pasos), registro (3 pasos), autenticador
│   │   ├── 6_panel_page.py         Resumen (con la descarga CSV)
│   │   ├── 7_personal_page.py      Datos personales
│   │   ├── 8_salud_page.py         Salud
│   │   ├── 9_credito_page.py       Crédito
│   │   ├── 10_seguridad_page.py    Seguridad
│   │   └── 3_A_page.py, 4_B_page.py, 5_C_page.py   páginas de equipos (plantilla original)
│   ├── panel.py                    vistas de las secciones de la cuenta
│   ├── session.py                  sesión autenticada (crear, validar, cerrar)
│   ├── services/
│   │   ├── accounts.py             registro, enrolamiento TOTP, login, bloqueo
│   │   └── export.py               CSV: permiso, columnas explícitas, neutralización
│   ├── security/
│   │   ├── passwords.py            política de contraseñas y Argon2id
│   │   └── otp.py                  TOTP, cifrado AES-256-GCM, QR
│   ├── db.py                       pool de conexiones (rol de la app)
│   ├── config.py                   lectura y validación de variables de entorno
│   ├── migrate.py                  CLI today-migrate
│   ├── migrations/                 0001_cuentas_otp_perfil_demo.sql, 0002_sin_roles_de_aplicacion.sql
│   ├── admin.py                    CLI today-admin (check, unlock, seed-demo)
│   ├── demo_data.py                generador de datos ficticios
│   ├── logging_setup.py            logs a stdout (journald en el servidor)
│   ├── team.py                     integrantes del equipo (carrusel del acceso)
│   └── ui/
│       ├── theme.py                componentes HTML (encabezados, baldosas, pasos, QR…)
│       ├── style.css               estilos y animaciones
│       └── favicon.png
└── tests/                          pytest con PostgreSQL real y streamlit.testing
```

### 3.4 Capas

| Capa | Archivos | Regla |
| --- | --- | --- |
| Presentación | `main.py`, `all_pages/`, `panel.py`, `ui/` | Solo muestra datos y llama a los servicios. No escribe SQL. |
| Sesión | `session.py` | Guarda el id de la cuenta y marcas de tiempo; relee la cuenta en cada ejecución. |
| Servicios | `services/accounts.py`, `services/export.py` | Toda la lógica de negocio y todas las consultas (parametrizadas). |
| Seguridad | `security/passwords.py`, `security/otp.py` | Funciones puras, sin base de datos: política, hash, TOTP, cifrado. |
| Datos | `db.py`, `config.py`, `migrations/`, `migrate.py` | Conexión, secretos y esquema versionado. |
| Administración | `admin.py`, `demo_data.py` | Tareas fuera de la web (verificación, desbloqueo, datos ficticios). |

### 3.5 Navegación

`main.py` decide qué páginas existen en cada ejecución con `st.navigation(..., position="hidden")`:

- **Sin sesión:** solo `2_auth_page.py`, como página por defecto.
- **Con sesión:** Resumen (página por defecto), Datos personales (`/datos`), Salud (`/salud`), Crédito (`/credito`), Seguridad (`/seguridad`) y los tres equipos.

Las dos páginas por defecto comparten la URL raíz, así que entrar o salir no cambia la URL. La navegación de Streamlit está oculta y la barra lateral propia usa `st.page_link`. El ítem activo se marca con un círculo rosa.

### 3.6 Estado de la sesión

`st.session_state` vive en la memoria del servidor y está ligado a la conexión del navegador; no son cookies. Las claves que usa la app:

| Clave | Contenido | Vida |
| --- | --- | --- |
| `_auth` | `user_id`, hora de emisión y última actividad | Hasta cerrar sesión, 30 min sin uso u 8 h |
| `_enroll_user_id` | Cuenta cuyo QR se está mostrando | Hasta activar, cancelar o vencer (10 min) |
| `_auth_view` | Pantalla actual del acceso (`login`, `code`, `register`, `demo`) | Mientras no haya sesión |
| `_login_pending` | Usuario y contraseña entre el paso 1 y el 2 del login | Máx. 5 min; se borra con cualquier resultado |
| `_reg_account` | Usuario, correo y contraseña entre el paso 1 y el 2 del registro | Máx. 15 min; se borra al crear la cuenta, volver atrás o vencer |
| `_reg_demo` | Datos de demostración guardados al volver al paso 1 | Hasta terminar o salir del registro |
| `_reg_errors`, `_flash` | Mensajes de error y avisos | Una ejecución |

Iniciar sesión vacía todo el estado antes de crear `_auth`, y cerrar sesión lo vacía entero.

Las acciones de los formularios se procesan en **callbacks**. Así se vacían los campos de contraseña y de código antes de volver a pintar la página, y esos valores no quedan en el estado de los widgets.

### 3.7 Interfaz

- **Sin piel de Streamlit:** la barra superior, el menú, la barra lateral nativa y la navegación están ocultos (`.streamlit/config.toml` + CSS).
- **Estilos:** `ui/style.css` se inyecta con `st.html("<style>…</style>")` en cada ejecución. No hay componentes React ni JavaScript propio.
- **Diseño:**
  - Tablero blanco sobre fondo nocturno a rayas.
  - Barra lateral azul noche.
  - Recuadro gris para el contenido.
  - Baldosas pastel (durazno, rosa, lila, menta, gris).
  - Tipografías Outfit y DM Mono.
  - Iconos de la fuente Material Symbols que ya trae Streamlit.
- **Acceso:** la columna derecha muestra los pasos del recorrido (el actual resaltado) y un carrusel continuo, hecho solo con CSS, con los integrantes del equipo (`team.py`). En los formularios largos esa columna acompaña al desplazarse.
- **Animaciones:**
  - Entrada del tablero y aparición escalonada de los bloques.
  - Baldosas y botones que reaccionan al ratón.
  - El QR que «se imprime» y la barra de puntaje que se llena.
  - Avisos de error con temblor.
  - Todas se desactivan con `prefers-reduced-motion`.
- **Responsive:** por debajo de 960 px la barra lateral pasa a ser una barra horizontal deslizable y las columnas se apilan. Por debajo de 640 px se compactan los márgenes.

---

## 4. Base de datos

### 4.1 Roles de PostgreSQL

La aplicación no tiene roles de usuario: todas las cuentas tienen los mismos permisos. Los únicos roles son los de PostgreSQL:

| Rol | Uso | Permisos |
| --- | --- | --- |
| `today_owner` | Migraciones y `today-admin unlock` | Dueño de la base `today` y del esquema `today`. `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`. |
| `today_app` | Conexión de Streamlit | Solo lo que conceden las migraciones (ver 4.4). Límite de 20 conexiones. |

`db/bootstrap.sql` los crea, junto con la base y los permisos de conexión, y quita los permisos de `PUBLIC`. Las contraseñas se fijan aparte con `\password`.

### 4.2 Tablas

**`today.app_user`**: cuentas, sin datos de demostración.

| Columna | Tipo | Descripción |
| --- | --- | --- |
| `id` | `bigint` identity | Clave primaria |
| `username` | `text` | Único; minúsculas; `^[a-z0-9][a-z0-9._-]{2,31}$` |
| `email` | `text` | Único; minúsculas; máx. 254 |
| `password_hash` | `text` | Argon2id en formato PHC (algoritmo, parámetros, sal y hash) |
| `created_at`, `last_login_at` | `timestamptz` | Creación y último inicio de sesión |
| `failed_attempts`, `locked_until` | `integer`, `timestamptz` | Intentos fallidos y bloqueo (persistentes) |
| `otp_enabled` | `boolean` | Segundo factor activo |
| `otp_secret_enc` | `bytea` | Semilla TOTP cifrada (AES-256-GCM) |
| `otp_last_step` | `bigint` | Último intervalo TOTP aceptado (evita reutilizar códigos) |
| `otp_pending_secret_enc`, `otp_pending_attempts`, `otp_pending_expires_at` | | Enrolamiento pendiente: semilla cifrada, intentos y vencimiento |

**`today.user_profile`**: datos de demostración, una fila por cuenta (`user_id` → `app_user.id`, `ON DELETE CASCADE`).

| Columna | Restricción |
| --- | --- |
| `full_name` | 3 a 120 caracteres |
| `document_id` | `^[0-9A-Za-z-]{5,20}$` |
| `birth_date` | Desde 1900-01-01 (la app exige además mayoría de edad) |
| `phone` | `^\+?[0-9 ]{7,20}$` |
| `city` | 2 a 80 caracteres |
| `blood_type` | O+, O-, A+, A-, B+, B-, AB+, AB- |
| `allergies`, `chronic_condition` | Máx. 200 caracteres |
| `credit_score` | 150 a 950 |
| `monthly_income`, `outstanding_debt` | `numeric(14,2)`, de 0 a 999.999.999.999 |

**`today.schema_migrations`**: versión, nombre, suma SHA-256 y fecha de cada migración aplicada. El rol de la app no puede leerla.

La base también impone las reglas con `CHECK`, aunque alguien se salte la validación de la app. Por ejemplo, un segundo factor activo exige una semilla guardada.

### 4.3 Permisos del rol de la aplicación

| Puede | No puede |
| --- | --- |
| `SELECT` en `app_user` y `user_profile` | `DELETE` ni `TRUNCATE` en ninguna tabla |
| `INSERT (username, email, password_hash)` en `app_user` | Cambiar `username` ni `email` |
| `UPDATE` solo de las columnas de login y OTP | Insertar `otp_enabled` u otras columnas de control |
| `INSERT` en `user_profile` | Modificar perfiles |
| | Crear, alterar o borrar objetos (DDL) |
| | Leer `schema_migrations` |

`today-admin check` lo comprueba en el servidor y las pruebas lo verifican sentencia por sentencia.

### 4.4 Migraciones

- Cada archivo `src/web_app/migrations/NNNN_nombre.sql` se aplica **una sola vez**, en su propia transacción, con el rol dueño.
- Cada una queda registrada con su suma SHA-256. Si un archivo ya aplicado cambia, `today-migrate` se detiene.
- Un bloqueo consultivo (`pg_advisory_lock`) impide dos ejecuciones simultáneas.
- `{{app_role}}` se sustituye por el rol de la app (`TODAY_APP_ROLE`), citado como identificador SQL.

| Versión | Qué hace |
| --- | --- |
| `0001_cuentas_otp_perfil_demo` | Crea `app_user`, `user_profile`, restricciones y permisos mínimos. |
| `0002_sin_roles_de_aplicacion` | Elimina la columna `role` (el enunciado no pide roles). Conserva todas las filas: probada sobre una base con 19 cuentas. |

Para un cambio de esquema se añade un archivo nuevo con el siguiente número. Nunca se edita uno ya aplicado.

```bash
uv run --env-file .env today-migrate status   # aplicadas y pendientes
uv run --env-file .env today-migrate          # aplica las pendientes
```

---

## 5. Seguridad

### 5.1 Controles, dónde están y qué prueba los cubre

| Control | Implementación | Pruebas |
| --- | --- | --- |
| Contraseñas con Argon2id y sal por contraseña | `security/passwords.py` | `test_argon2id_con_sal_distinta_y_verificacion` |
| Política de contraseñas | `check_policy` (ver 5.2) | `test_politica_rechaza`, `test_politica_acepta`, `test_normalizacion_nfkc` |
| Validación en el servidor | `validate_registration`, `validate_account` | `test_validacion_en_servidor`, `test_validate_account_solo_revisa_la_cuenta`, `test_registro_paso1_valida_y_borra_la_contrasena` |
| Duplicados con restricciones de PostgreSQL | `UNIQUE` + mensajes por restricción | `test_usuario_duplicado_sin_importar_mayusculas`, `test_correo_duplicado`, `test_registro_usuario_duplicado_vuelve_al_paso1` |
| Reglas también en la base | `CHECK` en ambas tablas | `test_restricciones_en_la_base` |
| Consultas parametrizadas | psycopg con `%s`; identificadores con `sql.Identifier` | En todo el código de `services/` |
| Permisos mínimos y rol separado para el esquema | `today_owner` / `today_app` + `GRANT` por columna | `test_rol_app_tiene_permisos_minimos` (10 sentencias), `test_cli_check_detecta_permisos_excesivos` |
| Migraciones versionadas que preservan filas | `migrate.py` | `test_migraciones_aplicadas_e_idempotentes`, `test_migracion_modificada_se_detecta`, `test_sin_columna_de_rol` |
| Una semilla TOTP por usuario, cifrada, con la clave fuera de PostgreSQL | `security/otp.py` + `TODAY_OTP_ENCRYPTION_KEY` | `test_enrolamiento_activa_y_cifra`, `test_cifrado_semilla_ligado_al_usuario` |
| QR visible solo para su usuario | Enrolamiento ligado a la sesión del navegador | `test_qr_solo_en_la_sesion_que_registra` |
| Activación tras confirmar un código | `confirm_enrollment` | `test_enrolamiento_activa_y_cifra` |
| Límite y vencimiento del enrolamiento | 5 intentos, 10 min | `test_enrolamiento_limite_de_intentos`, `test_enrolamiento_vencido`, `test_reinicio_de_enrolamiento` |
| Códigos como texto de 6 dígitos (ceros iniciales) | `normalize_code` | `test_codigo_conserva_ceros`, `test_otp_con_cero_inicial`, `test_codigo_con_cero_inicial_coincide` |
| Código vencido | Ventana ±1 intervalo | `test_otp_vencido`, `test_matching_step_ventana_y_vencido` |
| Código no reutilizable, ni con intentos simultáneos | `UPDATE … WHERE otp_last_step < paso` con la fila bloqueada | `test_otp_reutilizado`, `test_otp_reutilizado_en_paralelo` (4 hilos, 1 éxito) |
| Límite persistente de intentos por cuenta | `_register_failure` en PostgreSQL | `test_bloqueo_por_intentos_persistente` (sobrevive a reiniciar el pool), `test_bloqueo_con_intentos_en_paralelo` |
| Usuario + contraseña + OTP para crear la sesión | `authenticate` | `test_login_exige_los_tres_factores` (las 8 combinaciones), `test_login_campos_vacios`, `test_login_sin_otp_activo_falla`, `test_login_completo_y_cierre_de_sesion` |
| Mensajes genéricos y sin pistas por tiempo | Mismo mensaje; hash ficticio si la cuenta no existe | `test_paso2_error_generico`, `test_paso1_no_verifica_ni_cuenta_intentos` |
| Permiso comprobado al ejecutar la acción | `session.current_user` en cada ejecución; `build_csv` revisa la cuenta antes de consultar | `test_permiso_se_revisa_al_ejecutar`, `test_csv_no_consulta_datos_si_no_hay_permiso` |
| Sesión limpia al salir | `session.sign_out` vacía el estado | `test_login_completo_y_cierre_de_sesion` |
| Sin sesión no hay páginas ni descarga | Navegación condicional | `test_sin_sesion_no_hay_otras_paginas`, `test_sin_sesion_no_hay_descarga`, `test_csv_denegado` |
| CSV con columnas explícitas, sin secretos, con fórmulas neutralizadas | `services/export.py` | `test_csv_contenido`, `test_neutraliza_formulas` |
| Logs sin contraseñas, códigos, semillas ni datos de formulario | `event=… user_id=…` | `test_logs_sin_secretos` |
| Secretos, volcados y exportaciones fuera del repositorio | `.gitignore` + `.env.example` ficticio | Revisión con `git check-ignore` |

### 5.2 Detalle de los controles principales

**Política de contraseñas.**
- La contraseña se normaliza a Unicode NFKC antes de validarla y de calcular el hash.
- Debe tener entre 12 y 128 caracteres, al menos una letra, al menos un número o símbolo y al menos 6 caracteres distintos.
- No puede contener el usuario ni la parte local del correo.
- Se rechazan las contraseñas comunes y las palabras comunes rodeadas de números o símbolos (`Password2025!`, `Contraseña123`).
- No admite caracteres de control.

**Argon2id.**
- Parámetros: `t=3`, `m=64 MiB`, `p=4`, sal aleatoria de 16 bytes y hash de 32 bytes (perfil de RFC 9106).
- Si los parámetros cambian, el hash se recalcula en el siguiente inicio de sesión correcto.

**TOTP.**
- Usa 6 dígitos, intervalos de 30 s y acepta el intervalo actual ±1, es decir, ±30 s de desfase de reloj.
- La semilla tiene 160 bits. Se guarda como `0x01 ‖ nonce(12) ‖ cifrado AES-256-GCM`, con el id de la cuenta como dato asociado: una semilla copiada a otra fila no se puede descifrar.
- La comparación de códigos es de tiempo constante y recorre toda la ventana.

**Bloqueo.**
- Cada fallo suma un intento dentro de la misma transacción que bloqueó la fila (`SELECT … FOR UPDATE`).
- Al quinto fallo la cuenta queda bloqueada 15 minutos. Un login correcto pone el contador a cero.
- El contador vive en PostgreSQL: sobrevive a reinicios y no pierde intentos aunque lleguen en paralelo.

**Logs.** Van a stdout, y de ahí a journald en el servidor. Solo llevan el evento y el id interno de la cuenta:
- Acceso: `auth_ok`, `auth_failed` (con `reason`), `auth_rejected`.
- Registro: `register_ok`, `register_duplicate`.
- Enrolamiento: `enroll_started`, `enroll_activated`, `enroll_code_invalid`, `enroll_exhausted`, `enroll_expired`.
- Exportación: `export_ok`, `export_denied`.
- Errores de servicio: los eventos `*_unavailable`.

**Configuración endurecida de Streamlit.**
- Escucha solo en `127.0.0.1`.
- Protección XSRF activa.
- El navegador no muestra trazas de error (`showErrorDetails = "none"`).
- No se envían estadísticas de uso.
- Subidas limitadas a 1 MB.

**systemd** (`deploy/cyber.service`):
- La app corre como `ubuntu` y los secretos llegan por `EnvironmentFile`.
- Endurecimiento: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectKernel*`, `RestrictSUIDSGID` y `UMask=0077`.

---

## 6. Configuración

### 6.1 Variables de entorno

| Variable | Obligatoria | Uso |
| --- | --- | --- |
| `TODAY_DATABASE_URL` | Sí | Conexión del rol de la app (`today_app`). Ej.: `postgresql://today_app:…@IP:5432/today?sslmode=require&connect_timeout=5` |
| `TODAY_OTP_ENCRYPTION_KEY` | Sí | Clave AES-256 (32 bytes en base64) para cifrar semillas TOTP |
| `TODAY_APP_ROLE` | No (`today_app`) | Rol al que las migraciones conceden permisos |
| `TODAY_OTP_ISSUER` | No (`today`) | Nombre que muestra la app autenticadora |
| `TODAY_TIMEZONE` | No (`America/Bogota`) | Zona horaria de las fechas en pantalla |
| `TODAY_MIGRATOR_DATABASE_URL` | Solo para migrar o desbloquear | Conexión del rol dueño (`today_owner`). En el servidor no se guarda en archivos |

Generar la clave de cifrado:

```bash
uv run python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

`config.py` valida las variables al arrancar: si falta una o la clave no decodifica a 32 bytes, la app no se conecta.

> Si se pierde `TODAY_OTP_ENCRYPTION_KEY`, ninguna semilla se puede descifrar y nadie puede iniciar sesión hasta volver a enrolar el OTP. Guárdala en el gestor de secretos del equipo.

### 6.2 Archivos de configuración

| Archivo | Qué contiene | ¿En Git? |
| --- | --- | --- |
| `.env.example` | Nombres de las variables con valores ficticios | Sí |
| `.env` (local) / `/etc/today/today.env` (servidor) | Secretos reales | **No** (`.gitignore`) |
| `.streamlit/config.toml` | Dirección y puerto, XSRF, opciones de cliente, tema | Sí |

`.gitignore` también excluye volcados (`*.dump`, `*.pgdump`, `*.backup`, `*.sql.gz`, `dumps/`, `backups/`), exportaciones (`*.csv`, `*.xlsx`, `exports/`), `.streamlit/secrets.toml`, `*.pem` y `*.key`.

---

## 7. Cómo correrla en local

### 7.1 Requisitos

- [uv](https://docs.astral.sh/uv/). Instala Python 3.14 si no está.
- Docker (o un PostgreSQL 14+ de desarrollo; probado con 18).
- Una app autenticadora en el teléfono.

### 7.2 Primera vez

```bash
# 1. Dependencias
uv sync

# 2. PostgreSQL de desarrollo en Docker (solo escucha en 127.0.0.1)
docker run -d --name today-pg-dev -e POSTGRES_PASSWORD=solo-local \
  -p 127.0.0.1:55432:5432 postgres:18-alpine
docker exec -i today-pg-dev psql -U postgres -v ON_ERROR_STOP=1 < db/bootstrap.sql
docker exec today-pg-dev psql -U postgres \
  -c "ALTER ROLE today_owner PASSWORD 'local-owner'" \
  -c "ALTER ROLE today_app PASSWORD 'local-app'"

# 3. Variables de entorno
cp .env.example .env
```

Edita `.env` con valores locales:

```dotenv
TODAY_DATABASE_URL=postgresql://today_app:local-app@127.0.0.1:55432/today
TODAY_MIGRATOR_DATABASE_URL=postgresql://today_owner:local-owner@127.0.0.1:55432/today
TODAY_APP_ROLE=today_app
TODAY_OTP_ENCRYPTION_KEY=<la clave generada con el comando de la sección 6.1>
TODAY_OTP_ISSUER="today local"
TODAY_TIMEZONE=America/Bogota
```

```bash
# 4. Esquema y datos ficticios
uv run --env-file .env today-migrate
uv run --env-file .env today-admin seed-demo --count 12   # cuentas inventadas para el CSV
uv run --env-file .env today-admin check                  # debe decir "permisos mínimos: ok"

# 5. Arrancar
uv run --env-file .env streamlit run src/web_app/main.py
```

Abre <http://127.0.0.1:8501>, crea una cuenta, escanea el QR con tu app autenticadora e inicia sesión.

### 7.3 Día a día

```bash
docker start today-pg-dev                                     # si reiniciaste el equipo
uv run --env-file .env streamlit run src/web_app/main.py
```

- **Ver las trazas de error en el navegador:** antepón `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=full` al comando.
- **Cambios en los módulos:** Streamlit recarga las páginas de `all_pages/`, pero no los módulos de `web_app` (`theme.py`, `panel.py`, `services/`…). Tras cambiarlos, reinicia el servidor (Ctrl+C y el mismo comando).
- **Otro servidor ya usa el 8501:** añade `--server.port 8502`.
- **Empezar con la base vacía:** `docker rm -f today-pg-dev` y repite el paso 2 de 7.2.

---

## 8. Pruebas

```bash
# Sin base de datos: solo las pruebas unitarias (las de PostgreSQL se omiten)
uv run pytest

# Completas, contra un PostgreSQL de DESARROLLO
# (la contraseña es la de POSTGRES_PASSWORD con la que creaste el contenedor)
TODAY_TEST_ADMIN_URL='postgresql://postgres:solo-local@127.0.0.1:55432/postgres' uv run pytest
```

Las pruebas de base de datos:
1. Crean una base y dos roles temporales (dueño y aplicación).
2. Aplican las migraciones con el rol dueño.
3. Ejecutan la app con el rol de permisos mínimos.
4. Al terminar, borran la base y los roles.

Nunca tocan la base `today`. Las pruebas de interfaz usan `streamlit.testing` (AppTest) contra la app real.

Entre paréntesis, el número de funciones de prueba. Algunas se ejecutan con varios parámetros, por eso el total es mayor.

| Archivo | Cubre |
| --- | --- |
| `test_unit_security.py` (11) | Política de contraseñas, Argon2id, NFKC, códigos con ceros, ventana TOTP, cifrado ligado al usuario, neutralización CSV, validación del paso 1 |
| `test_auth_flows.py` (18) | Registro y duplicados, enrolamiento (activación, límite, vencimiento, reinicio), las 8 combinaciones de login, OTP con cero inicial, vencido y reutilizado (también en paralelo), bloqueo persistente y en paralelo, logs sin secretos |
| `test_db_schema.py` (8) | Migraciones idempotentes, detección de migraciones modificadas, permisos mínimos, `CHECK` en la base, columna `role` eliminada, `today-admin check` y `unlock` |
| `test_export_csv.py` (6) | Contenido exacto del CSV, sin secretos, fórmulas neutralizadas, cualquier cuenta con OTP puede descargar, denegado sin cuenta o sin OTP, permiso revisado antes de consultar |
| `test_ui.py` (21) | Login en dos pasos, registro en tres, QR solo en su sesión, páginas inexistentes sin sesión, descarga en el resumen, secciones y equipos con sesión, cierre de sesión |

Último resultado (PostgreSQL 18.6, Python 3.14.7, Streamlit 1.66.1): **123 passed**. Sin base de datos: 42 passed y 81 skipped.

> AppTest no ejecuta la validación que hace el navegador (por ejemplo, los límites de un `number_input`). Por eso los campos numéricos del registro no tienen límites en el navegador: el rango lo valida el servidor y el error sale bajo el campo.

---

## 9. Despliegue en el servidor

### 9.1 Entorno

| Pieza | Valor |
| --- | --- |
| Sistema y usuario | Ubuntu, usuario `ubuntu` |
| Clon | `/home/ubuntu/Developer/today` |
| Servicio | `cyber.service` (systemd) |
| Proxy | Nginx con HTTPS → `http://127.0.0.1:8501` (con WebSocket) |
| Base de datos | PostgreSQL en otra VM privada |
| Secretos | `/etc/today/today.env` (root:ubuntu, `0640`) |

### 9.2 Primera instalación

1. **Base de datos** (en la VM de PostgreSQL, una vez):

   ```bash
   sudo -u postgres psql -v ON_ERROR_STOP=1 -f bootstrap.sql
   sudo -u postgres psql -c '\password today_owner'
   sudo -u postgres psql -c '\password today_app'
   ```

   En `pg_hba.conf`, permite la base `today` solo desde la IP privada de la VM web, con `scram-sha-256`.

2. **Código y dependencias** (VM web, como `ubuntu`):

   ```bash
   cd /home/ubuntu/Developer/today
   git pull --ff-only
   uv sync --frozen --no-dev
   ```

3. **Secretos:**

   ```bash
   sudo install -d -m 0750 -o root -g ubuntu /etc/today
   sudo install -m 0640 -o root -g ubuntu .env.example /etc/today/today.env
   sudoedit /etc/today/today.env   # TODAY_DATABASE_URL, TODAY_OTP_ENCRYPTION_KEY (nueva), TODAY_APP_ROLE
   ```

4. **Migraciones** con el rol dueño. Su contraseña se pide y no se guarda:

   ```bash
   read -rsp "Clave de today_owner: " PGPASSWORD; echo; export PGPASSWORD
   export TODAY_MIGRATOR_DATABASE_URL='postgresql://today_owner@IP_PRIVADA_PG:5432/today'
   uv run --no-sync today-migrate status
   uv run --no-sync today-migrate
   unset PGPASSWORD TODAY_MIGRATOR_DATABASE_URL
   ```

5. **Servicio.** Compara `deploy/cyber.service` con la unidad actual (`systemctl cat cyber.service`). La propuesta añade:
   - `EnvironmentFile` con los secretos.
   - `WorkingDirectory` en el clon, porque Streamlit lee `.streamlit/config.toml` desde ahí.
   - `uv run --no-sync`, para que no instale nada al arrancar.
   - Endurecimiento de systemd.

   Ajusta la ruta de `uv` si `command -v uv` devuelve otra.

   ```bash
   sudo cp deploy/cyber.service /etc/systemd/system/cyber.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now cyber.service
   ```

6. **Opcional:** `deploy/nginx-sin-marca-streamlit.conf` evita que el título y el favicon de Streamlit se vean un instante antes de que cargue la app.

### 9.3 Actualizar una versión

```bash
cd /home/ubuntu/Developer/today
git pull --ff-only
uv sync --frozen --no-dev
# Si hay migraciones nuevas: haz antes una copia de seguridad en la VM de PostgreSQL
# (fuera del repositorio) y aplica el paso 4 de 9.2.
sudo systemctl restart cyber.service
```

Las migraciones no tienen marcha atrás automática. Por ejemplo, `0002` borra la columna `role`. Volver a una versión anterior del código después de migrar exige restaurar la copia de seguridad.

### 9.4 Prueba después del despliegue

```bash
systemctl status cyber.service --no-pager
curl -fsS http://127.0.0.1:8501/_stcore/health                    # → ok
curl -fsSI https://TU_DOMINIO/ | head -1                           # → HTTP/2 200
uv run --no-sync --env-file /etc/today/today.env today-admin check  # → permisos mínimos: ok
journalctl -u cyber.service -n 30 --no-pager
```

En el navegador, con datos ficticios:

1. La URL abre en **Inicia sesión**. Crea una cuenta: **Crea una** → **Siguiente** → **Llenar con datos ficticios** → **Crear cuenta**. Escanea el QR y activa el código.
2. Inicia sesión. Debe aparecer el Resumen, y `event=auth_ok` en journald.
3. Reutiliza el mismo código en otro intento: debe fallar con el mensaje genérico.
4. Pulsa **Descargar CSV**. Comprueba que no haya hashes ni semillas y que las celdas con `=` o `+` empiecen por `'`.
5. En una ventana privada, sin sesión, solo debe verse **Inicia sesión**.
6. **Cerrar sesión** debe volver a **Inicia sesión**.

---

## 10. Operación y solución de problemas

### 10.1 Comandos de administración

| Comando | Rol | Qué hace |
| --- | --- | --- |
| `today-migrate status` / `today-migrate` | `today_owner` | Muestra o aplica las migraciones |
| `today-admin check` | `today_app` | Valida la configuración, la conexión y los permisos mínimos |
| `today-admin unlock <usuario>` | `today_owner` | Quita un bloqueo por intentos antes de los 15 minutos |
| `today-admin seed-demo --count N [--seed S]` | `today_app` | Crea N cuentas con datos ficticios, por el mismo camino que el formulario. No imprime contraseñas |

Todos se ejecutan con `uv run --no-sync --env-file <archivo>` (o `uv run --env-file .env` en local).

### 10.2 Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| «No pudimos verificar tus datos» con datos correctos | Código ya usado, reloj del teléfono desfasado o cuenta bloqueada | Espera al siguiente código; sincroniza la hora del teléfono; `today-admin unlock` |
| El QR «venció» | Pasaron 10 minutos o se agotaron 5 intentos | Inicia sesión y pulsa **Configúralo** para obtener uno nuevo |
| «La verificación expiró» | Más de 5 minutos entre el paso 1 y el 2 del login | Vuelve a escribir usuario y contraseña |
| Un campo se pone rojo y no se envía el formulario | El navegador marcó el valor como inválido (por ejemplo, una fecha) | Corrige el valor del campo resaltado |
| «El servicio no está disponible» | PostgreSQL inaccesible o configuración incompleta | `journalctl -u cyber.service` (eventos `*_unavailable`) y `today-admin check` |
| `Port 8501 is not available` | Ya hay otro Streamlit corriendo | Detén el otro o usa `--server.port 8502` |
| Los cambios de estilo o de módulos no se ven | Streamlit no recarga los módulos de `web_app` | Reinicia el servidor |
| `today-migrate` dice que una migración «cambió» | Se editó un archivo ya aplicado | Revierte la edición y crea una migración nueva |

---

## 11. Decisiones y límites conocidos

- **Sin roles de aplicación.** El enunciado no los pide, así que cualquier cuenta con sesión puede descargar el CSV con todas las cuentas. Como el registro es abierto, cualquiera que cree una cuenta ve esos datos; por eso solo deben ser ficticios.
- **Contraseña en memoria entre pasos.** Para no revelar en el paso 1 si la contraseña es correcta, usuario y contraseña esperan en la sesión del servidor hasta el paso 2 (máx. 5 min en el login, 15 en el registro). Nunca se escriben en logs ni en la base en claro.
- **Sesiones en memoria.** Reiniciar el servicio cierra todas las sesiones. La app está pensada para una sola instancia de Streamlit.
- **Sin recuperación de cuenta.** No hay restablecimiento de contraseña, borrado de cuenta ni reinicio del segundo factor desde la web. Una cuenta con OTP activo que pierde el teléfono necesita que un administrador limpie su OTP en la base.
- **Clave de cifrado única.** No hay rotación automática de `TODAY_OTP_ENCRYPTION_KEY`; cambiarla obliga a volver a enrolar a todos.
- **TLS hacia PostgreSQL.** `.env.example` usa `sslmode=prefer`. Si la VM de PostgreSQL tiene certificado, usa `sslmode=require` (o `verify-full` con la CA) en `TODAY_DATABASE_URL`.
- **Marca de Streamlit al cargar.** El HTML inicial que sirve Streamlit trae su título y su favicon hasta que carga la app. El fragmento opcional de Nginx lo corrige.
- **Las migraciones avanzan, no retroceden.** Antes de migrar en el servidor, conviene una copia de seguridad (fuera del repositorio).
