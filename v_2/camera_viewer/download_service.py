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


def serve_forever(manager: RecordingDownloadManager | None = None) -> None:
    """Punto de entrada del servicio -- bloquea para siempre aceptando
    conexiones. Quien lo llama ya deberia ser dueño de SERVICE_LOCK_PATH
    (ver download_client.py._ensure_service_reachable); este modulo no
    vuelve a chequear el candado, solo sirve."""
    manager = manager or RecordingDownloadManager()
    authkey = get_or_create_authkey()
    # Sin authkey aqui a proposito: Listener.accept() haria el saludo de
    # autenticacion EN LINEA, dentro de este mismo hilo -- un solo cliente
    # lento o muerto a medio saludo dejaria sin atender a todos los demas.
    # El saludo (identico al que haria accept()) se hace en el hilo propio
    # de cada conexion, ver _handle_connection.
    listener = Listener(SERVICE_ADDRESS, backlog=LISTEN_BACKLOG)
    while True:
        conn = listener.accept()
        threading.Thread(target=_handle_connection, args=(manager, conn, authkey), daemon=True).start()


def _handle_connection(manager: RecordingDownloadManager, conn, authkey: bytes) -> None:
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
        elif action == "drain":
            manager.drain()
            _safe_send(conn, {"ok": True})
        else:
            _safe_send(conn, {"error": f"accion desconocida: {action!r}"})
    finally:
        conn.close()


def _handle_submit(manager: RecordingDownloadManager, conn, request: dict) -> None:
    # Un Event LOCAL a este proceso (el servicio) -- no cruza el socket.
    # Si el cliente se desconecta antes de que termine la descarga (ver
    # download_client.py: cierra la conexion cuando su propio stop_event
    # local se activa), este bucle lo detecta y activa ESTE Event, que es
    # el que de verdad hace que _play_chunk/_download corte la descarga a
    # medias -- el mismo mecanismo de siempre, solo que ahora el "cliente
    # que cancela" puede estar en otro proceso.
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

    while not future.done():
        if conn.poll(POLL_INTERVAL):
            try:
                conn.recv()
            except EOFError:
                stop_event.set()
                return
            # Cualquier otro mensaje (no deberia llegar en este protocolo)
            # se ignora y se sigue esperando a que la descarga termine.

    result = future.result()
    _safe_send(conn, {"path": str(result) if result is not None else None})


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
