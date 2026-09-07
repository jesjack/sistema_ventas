from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARCHIVO_MODO = BASE_DIR / "share" / "logs" / "modo_sistema.json"
ARCHIVO_RELANZAR = BASE_DIR / "share" / "logs" / "relanzar.flag"

MODOS_VALIDOS = ("normal", "ventas_dia")


def leer_modo() -> dict:
    try:
        datos = json.loads(ARCHIVO_MODO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"modo": "normal"}

    if not isinstance(datos, dict) or datos.get("modo") not in MODOS_VALIDOS:
        return {"modo": "normal"}

    return datos


def escribir_modo(modo: str, **extra) -> None:
    if modo not in MODOS_VALIDOS:
        raise ValueError(f"Modo desconocido: {modo!r}")

    datos = {"modo": modo, **extra}
    ARCHIVO_MODO.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_MODO.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def solicitar_relanzamiento() -> None:
    ARCHIVO_RELANZAR.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_RELANZAR.touch()
