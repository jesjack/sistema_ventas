from __future__ import annotations

import logging
import sys

# Registro de los contactos con el DVR (descargas y consultas ligeras): cuánto esperó cada
# pedido en la cola, cuánto tardó el DVR en dar el primer byte, cuánto duró, cuántos intentos
# hizo y por qué falló o se canceló. Nace del "los clips tardan en cargar" de 2026-09-21: sin
# estos tiempos no queda rastro para saber si la lentitud es de la cola, de la red o del DVR.
# Va a stderr, que el lanzador ya redirige a share/logs/camera_viewer/run_*.log.

logger = logging.getLogger("camera_viewer.dvr")


def enable(stream=None) -> None:
    """Activa el registro (lo llama el punto de entrada de la app y del servicio). Idempotente."""
    if logger.handlers:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [dvr] %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
