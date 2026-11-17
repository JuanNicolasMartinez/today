"""Registro de eventos de la aplicación (stdout → journald en el servidor).

Los mensajes solo incluyen el nombre del evento y el id interno de la cuenta.
No se registran contraseñas, códigos OTP, semillas ni datos de formularios.
"""

from __future__ import annotations

import logging
import sys

_configured = False


def configure() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("today")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True
