import logging

import streamlit as st

from web_app import logging_setup, session
from web_app.ui import theme

logging_setup.configure()
log = logging.getLogger("today.ui")

st.set_page_config(
    page_title="today",
    page_icon=theme.ICON,
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

# Sin sesión solo existe la página de acceso. Con sesión, el resumen pasa a ser
# la página por defecto y aparecen las secciones de la cuenta y los equipos.
# Las dos páginas por defecto comparten la URL raíz, así que entrar o salir no
# cambia de URL.
auth = st.Page("all_pages/2_auth_page.py", title="today · Acceso", default=True)
resumen = st.Page("all_pages/6_panel_page.py", title="today · Resumen", default=True)
personal = st.Page("all_pages/7_personal_page.py", title="today · Datos personales", url_path="datos")
salud = st.Page("all_pages/8_salud_page.py", title="today · Salud", url_path="salud")
credito = st.Page("all_pages/9_credito_page.py", title="today · Crédito", url_path="credito")
seguridad = st.Page("all_pages/10_seguridad_page.py", title="today · Seguridad", url_path="seguridad")
team_a = st.Page("all_pages/3_A_page.py", title="today · Equipo A")
team_b = st.Page("all_pages/4_B_page.py", title="today · Equipo B")
team_c = st.Page("all_pages/5_C_page.py", title="today · Equipo Chat")

ACCOUNT_LINKS = (
    (resumen, "Resumen", ":material/space_dashboard:", "resumen"),
    (personal, "Datos personales", ":material/badge:", "datos"),
    (salud, "Salud", ":material/ecg_heart:", "salud"),
    (credito, "Crédito", ":material/credit_card:", "credito"),
    (seguridad, "Seguridad", ":material/shield_lock:", "seguridad"),
)
TEAM_LINKS = (
    (team_a, "Equipo A", ":material/groups:", "team-a"),
    (team_b, "Equipo B", ":material/diversity_3:", "team-b"),
    (team_c, "Equipo Chat", ":material/forum:", "team-c"),
)


def _link(page: st.Page, label: str, icon: str, slug: str, current: st.Page) -> None:
    prefix = "rion" if page.url_path == current.url_path else "ri"
    with st.container(key=f"{prefix}-{slug}", width="content"):
        st.page_link(page, label=label, icon=icon, help=label)


def rail(current: st.Page, user) -> None:
    """Barra lateral: secciones de la cuenta, equipos, usuario y cierre de sesión."""
    theme.logo(compact=True)
    with st.container(key="rail", horizontal_alignment="center", gap=None):
        for item in ACCOUNT_LINKS:
            _link(*item, current)
        st.html('<span class="t-rail-sep" aria-hidden="true"></span>', width="content")
        for item in TEAM_LINKS:
            _link(*item, current)
        theme.avatar(user.username, size="sm")
        if st.button("Cerrar sesión", key="logout", icon=":material/logout:", help="Cerrar sesión"):
            session.sign_out()
            st.rerun()


def main() -> None:
    try:
        user = session.current_user()
    except Exception as exc:  # base de datos caída: se muestra el acceso
        log.error("event=session_unavailable error=%s", type(exc).__name__)
        user = None

    if user is None:
        pages = [auth]
    else:
        pages = [page for page, *_ in ACCOUNT_LINKS] + [page for page, *_ in TEAM_LINKS]
    pg = st.navigation(pages, position="hidden")
    theme.inject()

    with st.container(key="shell"):
        if user is None:
            pg.run()
        else:
            with st.container(key="frame", horizontal=True, gap=None, wrap=False):
                with st.container(key="side", width=96):
                    rail(pg, user)
                with st.container(key="stage"):  # el recuadro gris
                    pg.run()
    theme.footer()


if __name__ == "__main__":
    main()
