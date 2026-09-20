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
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
from pathlib import Path
from typing import Callable

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
    except (ConnectionRefusedError, FileNotFoundError, OSError, AuthenticationError, EOFError):
        return None


def _connect_or_bootstrap():
    """Camino rapido: conectar directo, sin candados ni sondeos previos --
    antes cada pedido abria una conexion de sondeo bajo un candado global
    ANTES de la real, duplicando las conexiones y serializando a todos los
    hilos (con backlog=1 en el servidor eso se traducia en esperas de
    varios segundos, o "nunca", ver download_service.LISTEN_BACKLOG). Solo
    si la conexion falla se recurre a _ensure_service_reachable()."""
    conn = _try_connect()
    if conn is not None:
        return conn
    _ensure_service_reachable()
    return _try_connect()


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
            threading.Thread(target=download_service.serve_forever, name="DownloadService", daemon=True).start()
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
    progress: Callable[[int], None] | None = None,
) -> Future:
    """Misma forma que RecordingDownloadManager.submit() -- ver ese
    docstring (incluido `progress`, que aquí se llama desde el hilo del pedido).
    Aqui la diferencia es toda interna: el pedido viaja por un
    socket a download_service.py en vez de encolarse directo."""
    message = {
        "action": "submit",
        "host": host,
        "username": username,
        "password": password,
        "channel": channel,
        "start": start,
        "end": end,
        "priority": priority,
    }
    if progress is not None:
        message["progress"] = True
    return _start_request(
        message, stop_event, lambda response: Path(response["path"]) if response.get("path") else None, progress
    )


def find_files(
    host: str,
    username: str,
    password: str,
    channel: int,
    start: datetime,
    end: datetime,
    max_pages: int,
    priority: int,
    stop_event: threading.Event,
) -> Future:
    """Búsqueda de grabaciones de un canal por el carril de consultas
    ligeras (ver LightQueryManager.submit_find_files). El Future se
    resuelve con la lista de diccionarios de cada archivo, o con una
    excepción si la consulta falló tras sus reintentos."""
    message = {
        "action": "query",
        "kind": "find_files",
        "host": host,
        "username": username,
        "password": password,
        "channel": channel,
        "start": start,
        "end": end,
        "max_pages": max_pages,
        "priority": priority,
    }
    return _start_request(message, stop_event, _decode_query_response)


def get(host: str, username: str, password: str, path: str, priority: int, stop_event: threading.Event) -> Future:
    """GET suelto de un CGI (p. ej. "cgi-bin/magicBox.cgi?action=getSystemInfo")
    por el carril de consultas ligeras; el Future trae el texto de la respuesta."""
    message = {
        "action": "query",
        "kind": "get",
        "host": host,
        "username": username,
        "password": password,
        "path": path,
        "priority": priority,
    }
    return _start_request(message, stop_event, _decode_query_response)


def _decode_query_response(response: dict):
    if "error" in response:
        raise RuntimeError(response["error"])
    return response["result"]


def _start_request(message: dict, stop_event: threading.Event, decode, progress=None) -> Future:
    future: Future = Future()
    threading.Thread(target=_run_request, args=(message, stop_event, decode, future, progress), daemon=True).start()
    return future


def _run_request(message: dict, stop_event: threading.Event, decode, future: Future, progress=None) -> None:
    """Manda el pedido y espera la respuesta. Descargas: un fallo de conexión
    con el servicio resuelve el Future con None (así lo espera la
    reproducción); consultas: lanza la excepción (decode la levanta)."""
    is_query = message["action"] == "query"

    def fail(reason: str) -> None:
        if is_query:
            future.set_exception(RuntimeError(reason))
        else:
            future.set_result(None)

    if stop_event.is_set():
        fail("cancelado")
        return
    conn = _connect_or_bootstrap()
    if conn is None:
        fail("no se pudo conectar con el servicio de descargas")
        return

    response = None
    try:
        conn.send(message)
        while True:
            if stop_event.is_set():
                # Cerrar la conexion es la señal de cancelacion: el
                # servicio la detecta como una desconexion (ver
                # download_service._wait_and_reply) y corta el trabajo en
                # curso -- sin necesidad de un segundo mensaje ni de tocar
                # esta misma conexion desde otro hilo.
                break
            if conn.poll(download_service.POLL_INTERVAL):
                try:
                    response = conn.recv()
                except EOFError:
                    response = None
                    break
                if isinstance(response, dict) and response.keys() == {"progress"}:
                    # Aviso de avance (solo si se pidió): no es la respuesta, se sigue esperando.
                    if progress is not None:
                        try:
                            progress(int(response["progress"]))
                        except Exception:
                            pass
                    response = None
                    continue
                break
    finally:
        conn.close()

    if response is None:
        fail("cancelado o sin respuesta del servicio")
        return
    try:
        future.set_result(decode(response))
    except Exception as exc:
        future.set_exception(exc)


class LiveLease:
    """Concesión de vista en vivo tomada al servicio (ver acquire_live_lease). La
    mantiene una conexión abierta: soltarla (release) o morir el proceso la libera."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


def acquire_live_lease(stop_event: threading.Event | None = None, timeout: float | None = None) -> LiveLease | None:
    """Pide al servicio que pause las descargas de grabaciones mientras dure la vista
    en vivo, y espera a que no quede ninguna en curso (ver
    download_service._handle_live_lease). Bloquea: llamarla desde un hilo aparte,
    no desde la interfaz. Devuelve None si el servicio no es alcanzable, si venció
    el tiempo con alguna descarga aún en curso, o si stop_event se activó."""
    wait = download_service.LIVE_LEASE_WAIT if timeout is None else timeout
    conn = _connect_or_bootstrap()
    if conn is None:
        return None
    try:
        conn.send({"action": "live_lease", "timeout": wait})
        deadline = time.monotonic() + wait + 5.0
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            if conn.poll(download_service.POLL_INTERVAL):
                if conn.recv().get("granted"):
                    return LiveLease(conn)
                break
    except (EOFError, OSError):
        pass
    conn.close()
    return None


def stats() -> dict | None:
    """Estado del carril de descargas del servicio: activas, en cola y concesiones de vivo."""
    conn = _connect_or_bootstrap()
    if conn is None:
        return None
    try:
        conn.send({"action": "stats"})
        return conn.recv().get("stats")
    except (EOFError, OSError):
        return None
    finally:
        conn.close()
