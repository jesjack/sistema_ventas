from __future__ import annotations

import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARCHIVO_MODO = BASE_DIR / "share" / "logs" / "modo_sistema.json"
ARCHIVO_RELANZAR = BASE_DIR / "share" / "logs" / "relanzar.flag"
ARCHIVO_INTENTOS_FALLO = BASE_DIR / "share" / "logs" / "relanzamientos_por_fallo.json"

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


def registrar_intento_relanzamiento_por_fallo(maximo: int, ventana_segundos: float, ahora: float | None = None) -> bool:
    """Cuenta un relanzamiento tras una salida inesperada del documento.

    Cada relanzamiento es un proceso main.py nuevo, así que el contador vive en
    disco. Devuelve True si todavía se permite relanzar (y lo cuenta) y False
    si ya se alcanzó `maximo` dentro de `ventana_segundos`, contados desde el
    último intento: si el sistema aguantó más que la ventana, se empieza de
    cero. Si no se puede escribir el contador también devuelve False, para no
    entrar en un ciclo de relanzamientos sin tope.
    """
    ahora = time.time() if ahora is None else ahora
    intentos, ultimo = 0, 0.0
    try:
        datos = json.loads(ARCHIVO_INTENTOS_FALLO.read_text(encoding="utf-8"))
        intentos, ultimo = int(datos["intentos"]), float(datos["ultimo"])
    except (OSError, ValueError, KeyError, TypeError):
        pass

    if ahora - ultimo > ventana_segundos:
        intentos = 0
    if intentos >= maximo:
        return False

    try:
        ARCHIVO_INTENTOS_FALLO.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVO_INTENTOS_FALLO.write_text(
            json.dumps({"intentos": intentos + 1, "ultimo": ahora}),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def reiniciar_intentos_relanzamiento_por_fallo() -> None:
    try:
        ARCHIVO_INTENTOS_FALLO.unlink()
    except OSError:
        pass
