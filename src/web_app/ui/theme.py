"""Componentes visuales hechos con Streamlit + CSS (sin React ni JavaScript).

Todo texto que venga del usuario pasa por ``esc`` antes de entrar en HTML.
Los iconos usan la fuente Material Symbols que ya trae Streamlit.
"""

from __future__ import annotations

import datetime as dt
import html
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

_HERE = Path(__file__).parent
ICON = str(_HERE / "favicon.png")

_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

# Marca: una píldora rosa y dos bloques blancos (las tres llaves) sobre un
# círculo azul noche. Es HTML y no SVG porque st.html elimina los <svg>.
_LOGO_HTML = '<i class="t-logo__a"></i><i class="t-logo__b"></i><i class="t-logo__c"></i>'


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


@lru_cache(maxsize=1)
def _display_tz() -> dt.tzinfo:
    try:
        return ZoneInfo(os.environ.get("TODAY_TIMEZONE", "America/Bogota"))
    except (ZoneInfoNotFoundError, ValueError):
        return dt.UTC


def _local(value: dt.datetime) -> dt.datetime:
    return value.astimezone(_display_tz())


def fmt_dt(value: dt.datetime | None) -> str:
    """Fecha y hora en la zona de visualización (TODAY_TIMEZONE)."""
    return _local(value).strftime("%d/%m/%Y %H:%M") if value else "—"


def fmt_day(value: dt.date | dt.datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, dt.datetime):
        value = _local(value)
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def fmt_time(value: dt.datetime | None) -> str:
    return _local(value).strftime("%H:%M") if value else "—"


def minutes_left(value: dt.datetime) -> int:
    return max(0, int((value - dt.datetime.now(dt.UTC)).total_seconds() // 60))


def initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s._-]+", name.strip()) if p]
    if not parts:
        return "?"
    letters = parts[0][0] + (parts[-1][0] if len(parts) > 1 else parts[0][1:2])
    return letters.upper()


def _stylesheet() -> str:
    # Se lee en cada ejecución (≈30 KB): así un cambio de estilo no exige reiniciar.
    return (_HERE / "style.css").read_text(encoding="utf-8")


def inject() -> None:
    st.html(f"<style>{_stylesheet()}</style>")


def icon(name: str) -> str:
    """Icono de Material Symbols (nombre en minúsculas, p. ej. ``lock``)."""
    return f'<span class="t-ico" aria-hidden="true">{esc(name)}</span>'


# --------------------------------------------------------------------------
# Marca, encabezados y avisos
# --------------------------------------------------------------------------


def logo(*, compact: bool = False) -> None:
    name = "" if compact else '<span class="t-logo__name">today</span>'
    mod = " t-logo--compact" if compact else ""
    st.html(f'<div class="t-logo{mod}"><span class="t-logo__mark" aria-hidden="true">{_LOGO_HTML}</span>{name}</div>')


def avatar(name: str, *, size: str = "md") -> None:
    st.html(
        f'<div class="t-avatar t-avatar--{esc(size)}" title="@{esc(name)}" aria-hidden="true">'
        f"{esc(initials(name))}</div>",
        width="content",
    )


def heading(title: str, sub: str | None = None, *, level: int = 1) -> None:
    tag = "h1" if level == 1 else "h2"
    sub_html = f'<p class="t-sub">{esc(sub)}</p>' if sub else ""
    st.html(f'<div class="t-heading t-heading--{level}"><{tag} class="t-h">{esc(title)}</{tag}>{sub_html}</div>')


def notice(message: str, tone: str = "neutral") -> None:
    """Aviso con animación de entrada. ``tone``: neutral, ok, warn, error, demo."""
    glyph = {"ok": "check_circle", "warn": "schedule", "error": "error", "demo": "science"}.get(tone, "info")
    st.html(
        f'<div class="t-notice t-notice--{esc(tone)}" role="status">'
        f'{icon(glyph)}<p>{esc(message)}</p></div>'
    )


def field_error(message: str | None) -> None:
    if message:
        st.html(f'<p class="t-field-error" role="alert">{esc(message)}</p>')


def hint(text: str) -> None:
    st.html(f'<p class="t-hint">{icon("info")}<span>{esc(text)}</span></p>')


def text_row(text: str) -> None:
    st.html(f'<span class="t-row-text">{esc(text)}</span>', width="content")


def group_title(glyph: str, title: str, tag: str | None = None) -> None:
    tag_html = f'<span class="t-tag">{esc(tag)}</span>' if tag else ""
    st.html(
        f'<div class="t-group"><span class="t-group__ico">{icon(glyph)}</span>'
        f'<span class="t-group__title">{esc(title)}</span>{tag_html}</div>'
    )


@dataclass(frozen=True)
class Step:
    title: str
    detail: str
    glyph: str
    tone: str  # peach, pink, lilac, mint


def journey(steps: Sequence[Step], current: int) -> None:
    """Tarjetas pastel con el recorrido; la actual resaltada y las anteriores marcadas."""
    items = []
    for i, s in enumerate(steps):
        state = "done" if i < current else "now" if i == current else "next"
        mark = icon("check") if state == "done" else str(i + 1)
        label = {"done": "Hecho", "now": "Ahora", "next": "Después"}[state]
        aria = ' aria-current="step"' if state == "now" else ""
        items.append(
            f'<li class="t-step t-step--{esc(s.tone)} is-{state}" style="--i:{i}"{aria}>'
            f'<span class="t-step__n">{mark}</span>'
            f'<span class="t-step__text"><span class="t-step__state">{label}</span>'
            f"<strong>{esc(s.title)}</strong><span>{esc(s.detail)}</span></span>"
            f'<span class="t-step__ico">{icon(s.glyph)}</span></li>'
        )
    st.html(f'<ol class="t-journey">{"".join(items)}</ol>')


_TEAM_TONES = ("pink", "peach", "lilac", "mint", "fog")


def team(names: Sequence[str]) -> None:
    """Carrusel continuo (solo CSS) con una tarjeta por integrante.

    La lista se repite una vez, oculta para lectores de pantalla, para que el
    desplazamiento no tenga saltos.
    """

    def cards(hidden: bool) -> str:
        attr = ' aria-hidden="true"' if hidden else ""
        return "".join(
            f'<li class="t-member t-member--{_TEAM_TONES[i % len(_TEAM_TONES)]}"{attr}>'
            f'<span class="t-member__face">{esc(initials(n))}</span>'
            f'<span class="t-member__name">{esc(n)}</span></li>'
            for i, n in enumerate(names)
        )

    st.html(
        '<section class="t-team" aria-label="Integrantes del equipo">'
        f'<p class="t-team__head"><span>Equipo</span><span>{len(names)} integrantes</span></p>'
        f'<div class="t-team__viewport"><ul class="t-team__track" style="--n:{len(names)}">'
        f"{cards(False)}{cards(True)}</ul></div></section>"
    )


# --------------------------------------------------------------------------
# Mosaico de baldosas pastel
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Tile:
    label: str
    value: str | None = None
    glyph: str | None = None
    tone: str = "white"  # white, peach, pink, lilac, mint, fog
    wide: bool = False
    tall: bool = False
    on: bool = False
    person: str | None = None  # si se da, la baldosa muestra iniciales en vez de icono


def _tile(t: Tile, i: int) -> str:
    cls = ["t-tile", f"t-tile--{t.tone}"]
    cls += [c for c, flag in (("is-wide", t.wide), ("is-tall", t.tall), ("is-on", t.on),
                              ("is-person", t.person is not None)) if flag]
    if t.person is not None:
        media = f'<span class="t-tile__face">{esc(initials(t.person))}</span>'
    elif t.glyph:
        media = f'<span class="t-tile__ico">{icon(t.glyph)}</span>'
    else:
        media = ""
    value = f'<span class="t-tile__value">{esc(t.value)}</span>' if t.value is not None else ""
    return (
        f'<div class="{" ".join(cls)}" style="--i:{i}">{media}'
        f'<span class="t-tile__text"><span class="t-tile__label">{esc(t.label)}</span>{value}</span></div>'
    )


def mosaic(tiles: Iterable[Tile], *, cols: int = 4) -> None:
    body = "".join(_tile(t, i) for i, t in enumerate(tiles))
    st.html(f'<div class="t-mosaic" style="--cols:{int(cols)}">{body}</div>')


def boxes(rows: Sequence[tuple[str, str]]) -> None:
    body = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in rows)
    st.html(f'<dl class="t-boxes">{body}</dl>')


def score_bar(value: int | None, lo: int, hi: int) -> None:
    if value is None:
        return
    pct = round(100 * (value - lo) / (hi - lo))
    st.html(
        f'<div class="t-score" style="--pct:{max(0, min(100, pct))}%">'
        f'<div class="t-score__head"><span>Puntaje de crédito</span><strong>{int(value)}</strong></div>'
        f'<span class="t-score__track"><span class="t-score__fill"></span></span>'
        f'<div class="t-score__scale"><span>{lo}</span><span>{hi}</span></div></div>'
    )


def export_text(glyph: str, title: str, detail: str) -> None:
    st.html(
        f'<div class="t-export"><span class="t-export__ico">{icon(glyph)}</span>'
        f'<span class="t-export__text"><strong>{esc(title)}</strong><span>{esc(detail)}</span></span></div>'
    )


def secret_key(secret_grouped: str) -> None:
    st.html(
        '<div class="t-secret"><span class="t-secret__label">¿No puedes escanear? Escribe esta clave</span>'
        f'<code class="t-secret__value">{esc(secret_grouped)}</code></div>'
    )


def qr(png_b64: str, username: str) -> None:
    st.html(
        '<figure class="t-qr">'
        f'<span class="t-qr__frame"><img src="data:image/png;base64,{png_b64}" '
        f'alt="Código QR para {esc(username)}" width="232" height="232"></span>'
        f'<figcaption>@{esc(username)}</figcaption></figure>'
    )


def footer() -> None:
    st.html(
        '<footer class="t-footer"><span>© Super Proyecto de Ciber</span>'
    )
