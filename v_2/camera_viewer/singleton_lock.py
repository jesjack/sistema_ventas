from __future__ import annotations

import sys
from pathlib import Path
from typing import IO


def acquire_singleton_lock(lock_path: Path) -> IO | None:
    """Bloqueo de instancia unica basado en un lock de archivo
    (flock/msvcrt) -- el sistema operativo lo libera solo si el proceso
    muere de golpe (kill -9, crash), asi que nunca queda un lock "trabado"
    que haya que limpiar a mano. Devuelve el file handle (hay que
    mantenerlo abierto mientras se quiera seguir siendo el dueño del
    candado) o None si ya hay otro dueño.

    Usado tanto por camera_viewer/__main__.py (una sola ventana de la app
    a la vez) como por download_service.py (un solo proceso sirviendo
    descargas a la vez, sin importar cual de los procesos que lo
    necesitan termine ganando la carrera por serlo)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file
