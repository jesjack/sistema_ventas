"""Servicio de descargas de grabaciones: un programa APARTE (no un modulo
que cada proceso instancia por su cuenta) que envuelve una unica instancia
de RecordingDownloadManager (ver download_manager.py) detras de un socket
local. Nace de una limitacion real: un semaforo o una cola de prioridad
que vive en la memoria de un proceso solo puede coordinar hilos DENTRO de
ese mismo proceso -- si dos procesos Python separados (la app de camaras y,
mas adelante, un archivador en segundo plano corriendo aparte) descargan
cada uno por su cuenta, cada uno con su propio limite de 2, entre los dos
pueden sumar 4 sesiones reales contra el DVR sin que ninguno se entere del
otro -- exactamente el umbral que lo tumba (ver informes/
DVR_STRESS_TEST_RESULTS.md). Con un unico servicio real, la cola de
prioridad vuelve a ser una cola de verdad (no una aproximacion con
archivos de bloqueo compartidos) sin importar cuantos procesos separados
le pidan descargas.

No hace falta arrancarlo a mano: cualquier proceso que necesite descargar
algo (ver download_client.py) intenta conectarse, y si no encuentra a
nadie escuchando, se postula el mismo para serlo (protegido por el mismo
candado de instancia unica que usa la ventana de la app, ver
singleton_lock.py) -- el primero que lo necesita, lo levanta, y se queda
sirviendo en un hilo de fondo de ESE proceso mientras viva. Tambien se
puede correr explicitamente como proceso propio (`python -m
camera_viewer.download_service`), por ejemplo para un futuro servicio de
guardado en segundo plano que deba seguir corriendo con la app de camaras
cerrada.
"""
from __future__ import annotations

import os
import threading
from multiprocessing import AuthenticationError
from multiprocessing.connection import Listener, answer_challenge, deliver_challenge
from pathlib import Path

from .download_manager import RecordingDownloadManager
from .light_query_manager import LightQueryManager

SERVICE_HOST = "localhost"
SERVICE_PORT = int(os.environ.get("DOWNLOAD_SERVICE_PORT", "51820"))
SERVICE_ADDRESS = (SERVICE_HOST, SERVICE_PORT)

# Localhost-only, pero igual amerita una clave (multiprocessing.connection
# la exige para aceptar una conexion) -- se genera una vez por maquina y se
# guarda con permisos restringidos, en vez de una clave fija en el codigo
# fuente. Cualquier proceso que necesite conectarse la lee del mismo
# archivo (ver download_client.py).
AUTHKEY_PATH = Path(__file__).resolve().parent.parent / "runtime" / "download_service.authkey"
SERVICE_LOCK_PATH = Path(__file__).resolve().parent.parent / "runtime" / "download_service.lock"

# Cuanto esperar por una respuesta del cliente (poll no bloqueante en un
# bucle) antes de volver a chequear si el pedido ya termino -- mismo estilo
# que RECORDING_BACKPRESSURE_POLL en dvr_client.py.
POLL_INTERVAL = 0.2

# Listener() usa backlog=1 por defecto: con una rafaga de pedidos (4 canales
# x [bloque actual + pre-descarga], y cada uno abriendo mas de una conexion)
# el kernel descarta los SYN que no caben y el cliente los reintenta a
# 1s/3s/7s/... -- se midio que 16 conexiones simultaneas ni siquiera
# terminaban en 60s (2026-09-18, "algunas grabaciones nunca se descargan").
LISTEN_BACKLOG = 128

# Cuánto espera el servicio, al pedirle una concesión de vivo, a que terminen las
# descargas en curso: el timeout de una descarga es 30 s (+ su pausa de cortesía).
LIVE_LEASE_WAIT = 60.0


def get_or_create_authkey() -> bytes:
    AUTHKEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 'x' falla si ya existe -- evita una condicion de carrera donde dos
        # procesos generan claves DISTINTAS al mismo tiempo y ya no se
        # pueden hablar entre si.
        with open(AUTHKEY_PATH, "xb") as fh:
            key = os.urandom(32)
            fh.write(key)
        os.chmod(AUTHKEY_PATH, 0o600)
        return key
    except FileExistsError:
        return AUTHKEY_PATH.read_bytes()


def serve_forever(
    manager: RecordingDownloadManager | None = None, light_manager: LightQueryManager | None = None
) -> None:
    """Punto de entrada del servicio -- bloquea para siempre aceptando
    conexiones. Quien lo llama ya deberia ser dueño de SERVICE_LOCK_PATH
    (ver download_client.py._ensure_service_reachable); este modulo no
    vuelve a chequear el candado, solo sirve. Hay DOS carriles
    independientes hacia el DVR: descargas de clips (manager) y consultas
    ligeras (light_manager, ver light_query_manager.py)."""
    manager = manager or RecordingDownloadManager()
    light_manager = light_manager or LightQueryManager()
    authkey = get_or_create_authkey()
    # Sin authkey aqui a proposito: Listener.accept() haria el saludo de
    # autenticacion EN LINEA, dentro de este mismo hilo -- un solo cliente
    # lento o muerto a medio saludo dejaria sin atender a todos los demas.
    # El saludo (identico al que haria accept()) se hace en el hilo propio
    # de cada conexion, ver _handle_connection.
    listener = Listener(SERVICE_ADDRESS, backlog=LISTEN_BACKLOG)
    while True:
        conn = listener.accept()
        threading.Thread(target=_handle_connection, args=(manager, light_manager, conn, authkey), daemon=True).start()


def _handle_connection(manager: RecordingDownloadManager, light_manager: LightQueryManager, conn, authkey: bytes) -> None:
    try:
        deliver_challenge(conn, authkey)
        answer_challenge(conn, authkey)
        request = conn.recv()
    except (AuthenticationError, EOFError, OSError):
        conn.close()
        return

    try:
        action = request.get("action")
        if action == "submit":
            _handle_submit(manager, conn, request)
        elif action == "query":
            _handle_query(light_manager, conn, request)
        elif action == "live_lease":
            _handle_live_lease(manager, conn, request)
        elif action == "stats":
            _safe_send(conn, {"stats": manager.stats()})
        else:
            _safe_send(conn, {"error": f"accion desconocida: {action!r}"})
    finally:
        conn.close()


def _handle_submit(manager: RecordingDownloadManager, conn, request: dict) -> None:
    # Un Event LOCAL a este proceso (el servicio) -- no cruza el socket.
    # Si el cliente se desconecta antes de que termine el trabajo (ver
    # download_client.py: cierra la conexion cuando su propio stop_event
    # local se activa), _wait_and_reply lo detecta y activa ESTE Event, que
    # es el que de verdad hace que _download corte la descarga a medias --
    # el mismo mecanismo de siempre, solo que ahora el "cliente que
    # cancela" puede estar en otro proceso.
    stop_event = threading.Event()
    future = manager.submit(
        request["host"],
        request["username"],
        request["password"],
        request["channel"],
        request["start"],
        request["end"],
        request["priority"],
        stop_event,
    )
    _wait_and_reply(conn, future, stop_event, lambda result: {"path": str(result) if result is not None else None})


def _handle_query(light_manager: LightQueryManager, conn, request: dict) -> None:
    """Consultas ligeras. `kind`: "get" (un GET suelto, responde su texto) o
    "find_files" (búsqueda completa de mediaFileFind, responde la lista de
    archivos). Un fallo (agotados los reintentos) se responde como
    {"error": mensaje} y el cliente lo convierte en excepción."""
    stop_event = threading.Event()
    kind = request.get("kind")
    common = (request["host"], request["username"], request["password"])
    if kind == "get":
        future = light_manager.submit_get(*common, request["path"], request["priority"], stop_event)
    elif kind == "find_files":
        future = light_manager.submit_find_files(
            *common,
            request["channel"],
            request["start"],
            request["end"],
            request["max_pages"],
            request["priority"],
            stop_event,
        )
    else:
        _safe_send(conn, {"error": f"consulta desconocida: {kind!r}"})
        return
    _wait_and_reply(conn, future, stop_event, lambda result: {"result": result})


def _handle_live_lease(manager: RecordingDownloadManager, conn, request: dict) -> None:
    """Concesión de vista en vivo (ver RecordingDownloadManager.acquire_live):
    mientras esta conexión siga abierta, no arranca ninguna descarga de
    grabación. Responde {"granted": True} cuando ya no queda ninguna en curso
    (o False si venció el tiempo). La concesión se suelta cuando el cliente
    cierra la conexión -- también si su proceso muere, sin necesidad de
    latidos ni temporizadores."""
    granted = manager.acquire_live(timeout=request.get("timeout", LIVE_LEASE_WAIT))
    _safe_send(conn, {"granted": granted})
    if not granted:
        return
    try:
        while True:
            try:
                if conn.poll(POLL_INTERVAL):
                    conn.recv()  # no debería llegar nada; EOF = el cliente soltó la concesión
            except (EOFError, OSError):
                return
    finally:
        manager.release_live()


def _wait_and_reply(conn, future, stop_event: threading.Event, encode) -> None:
    while not future.done():
        if conn.poll(POLL_INTERVAL):
            try:
                conn.recv()
            except EOFError:
                stop_event.set()
                return
            # Cualquier otro mensaje (no deberia llegar en este protocolo)
            # se ignora y se sigue esperando a que el trabajo termine.

    error = future.exception()
    _safe_send(conn, {"error": str(error) or type(error).__name__} if error else encode(future.result()))


def _safe_send(conn, message: dict) -> None:
    try:
        conn.send(message)
    except (BrokenPipeError, OSError):
        pass  # el cliente ya se fue, no hay a quien contestarle


if __name__ == "__main__":
    from .singleton_lock import acquire_singleton_lock

    lock_file = acquire_singleton_lock(SERVICE_LOCK_PATH)
    if lock_file is None:
        print("download_service ya esta corriendo; no se abre otra instancia.")
    else:
        print(f"download_service escuchando en {SERVICE_ADDRESS}...")
        serve_forever()
