"""Cliente del servicio de descargas (ver download_service.py). Expone la
misma forma que RecordingDownloadManager.submit() (mismos parametros,
devuelve un concurrent.futures.Future) para que DVRClient no note ninguna
diferencia al usarlo -- por dentro, cada llamada abre una conexion propia
al servicio, manda el pedido, y espera la respuesta en un hilo dedicado.

No hace falta que nadie arranque el servicio a mano: la primera vez que
este modulo necesita hablarle y no encuentra a nadie escuchando, se
postula el mismo para serlo (protegido por singleton_lock, el mismo
candado de instancia unica que usa __main__.py) -- pierde la carrera si
otro proceso ya gano el candado un instante antes, y en ese caso
simplemente reintenta conectarse (deberia estar listo enseguida)."""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from datetime import datetime
from multiprocessing.connection import Client
from pathlib import Path

from . import download_service
from .singleton_lock import acquire_singleton_lock

# Cuanto esperar entre "intento de conectarme" y "intento de volverme el
# host" antes de rendirse y avisar al llamador con un Future(None) --
# generoso a proposito: si el proceso que gano la carrera por ser host
# tarda un poco en arrancar el Listener, no queremos que el resto se de
# por vencido de inmediato.
CONNECT_RETRY_TIMEOUT = 5.0
CONNECT_RETRY_INTERVAL = 0.2

_bootstrap_lock = threading.Lock()
_hosting_lock_file = None  # si no es None, ESTE proceso es el que sirve


def _try_connect():
    try:
        authkey = download_service.get_or_create_authkey()
        return Client(download_service.SERVICE_ADDRESS, authkey=authkey)
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return None


def _ensure_service_reachable() -> None:
    """Garantiza que, al volver, o bien ya hay un servicio escuchando, o
    bien ESTE proceso se acaba de convertir en el servicio (en un hilo de
    fondo propio). No bloquea para siempre: si ninguna de las dos cosas se
    logra dentro de CONNECT_RETRY_TIMEOUT, simplemente vuelve (el llamador
    vera fallar su propio intento de conexion y lo tratara como error de
    red, igual que cualquier otro)."""
    global _hosting_lock_file

    with _bootstrap_lock:
        if _hosting_lock_file is not None:
            return  # este mismo proceso ya es el host

        conn = _try_connect()
        if conn is not None:
            conn.close()
            return  # ya hay alguien sirviendo

        lock_file = acquire_singleton_lock(download_service.SERVICE_LOCK_PATH)
        if lock_file is not None:
            # Ganamos la carrera: nos volvemos el host. El file handle debe
            # seguir abierto mientras sirvamos -- guardarlo en el global es
            # lo que evita que otro proceso (o este mismo, en una llamada
            # futura) crea que el puesto sigue libre.
            _hosting_lock_file = lock_file
            manager = download_service.RecordingDownloadManager()
            threading.Thread(
                target=download_service.serve_forever, args=(manager,), name="DownloadService", daemon=True
            ).start()
            deadline = time.monotonic() + CONNECT_RETRY_TIMEOUT
            while time.monotonic() < deadline:
                conn = _try_connect()
                if conn is not None:
                    conn.close()
                    return
                time.sleep(CONNECT_RETRY_INTERVAL)
            return

        # Perdimos la carrera -- alguien mas la gano un instante antes y
        # deberia estar levantando el Listener ahora mismo. Reintentar
        # conectarse en vez de intentar el candado de nuevo.
        deadline = time.monotonic() + CONNECT_RETRY_TIMEOUT
        while time.monotonic() < deadline:
            conn = _try_connect()
            if conn is not None:
                conn.close()
                return
            time.sleep(CONNECT_RETRY_INTERVAL)


def submit(
    host: str,
    username: str,
    password: str,
    channel: int,
    start: datetime,
    end: datetime,
    priority: int,
    stop_event: threading.Event,
) -> Future:
    """Misma forma que RecordingDownloadManager.submit() -- ver ese
    docstring. Aqui la diferencia es toda interna: el pedido viaja por un
    socket a download_service.py en vez de encolarse directo."""
    future: Future = Future()
    threading.Thread(
        target=_run_request,
        args=(host, username, password, channel, start, end, priority, stop_event, future),
        daemon=True,
    ).start()
    return future


def _run_request(
    host: str,
    username: str,
    password: str,
    channel: int,
    start: datetime,
    end: datetime,
    priority: int,
    stop_event: threading.Event,
    future: Future,
) -> None:
    _ensure_service_reachable()
    conn = _try_connect()
    if conn is None:
        future.set_result(None)
        return

    try:
        conn.send(
            {
                "action": "submit",
                "host": host,
                "username": username,
                "password": password,
                "channel": channel,
                "start": start,
                "end": end,
                "priority": priority,
            }
        )
        result = None
        while True:
            if stop_event.is_set():
                # Cerrar la conexion es la señal de cancelacion: el
                # servicio la detecta como una desconexion (ver
                # download_service._handle_submit) y corta la descarga en
                # curso -- sin necesidad de un segundo mensaje ni de tocar
                # esta misma conexion desde otro hilo.
                break
            if conn.poll(download_service.POLL_INTERVAL):
                try:
                    response = conn.recv()
                except EOFError:
                    break
                result = response.get("path")
                break
    finally:
        conn.close()

    future.set_result(Path(result) if result else None)


def drain() -> None:
    """Bloquea hasta que el servicio confirme que no hay ninguna descarga
    en curso -- ver DVRClient.start_live. Si no hay servicio corriendo (ni
    nada que drenar), no hay nada que hacer."""
    _ensure_service_reachable()
    conn = _try_connect()
    if conn is None:
        return
    try:
        conn.send({"action": "drain"})
        conn.recv()
    except (EOFError, OSError):
        pass
    finally:
        conn.close()
