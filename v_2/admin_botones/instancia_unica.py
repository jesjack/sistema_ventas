"""Que un segundo clic en "ADMINISTRAR ADMINS" traiga al frente la ventana ya abierta, en vez de
abrir otra encima -- sin depender de Qt en el lado que hace el lanzamiento (nucleo/botones.py
corre dentro del Python embebido de LibreOffice, que no tiene PySide6 instalado), así que la
señal entre procesos es un socket Unix simple, biblioteca estándar únicamente.

El lado que SÍ tiene Qt (admin_botones, ver ventana_botones.py/__main__.py) escucha en este mismo
socket desde un hilo aparte y, al recibir cualquier conexión, activa la ventana -- nunca toca la
UI directo desde ese hilo (ver Signal.emit(), thread-safe hacia el hilo principal de Qt)."""

from __future__ import annotations

import socket
from pathlib import Path


def _ruta_socket(base_dir) -> Path:
    ruta = Path(base_dir) / "share" / "runtime" / "admin_botones.sock"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return ruta


def hay_instancia_activa(base_dir) -> bool:
    """Si ya hay una ventana de admin_botones corriendo, le manda un ping (que ella interpreta
    como "traer al frente") y devuelve True -- el llamador no debe lanzar otro proceso. Si el
    archivo de socket es de una corrida anterior que no cerró limpio (el proceso murió sin poder
    borrarlo), la conexión falla y se considera que NO hay instancia activa, quitando el archivo
    viejo para no dejar bloqueado ningún lanzamiento futuro."""
    ruta = _ruta_socket(base_dir)
    if not ruta.exists():
        return False

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as cliente:
            cliente.settimeout(1.0)
            cliente.connect(str(ruta))
            cliente.sendall(b"traer_al_frente")
        return True
    except OSError:
        try:
            ruta.unlink()
        except OSError:
            pass
        return False


def escuchar(base_dir, al_recibir_ping) -> None:
    """Pensado para correr en un hilo daemon aparte, dentro de admin_botones: por cada conexión
    que llegue (siempre de hay_instancia_activa, nunca con datos que importe leer) llama a
    al_recibir_ping() sin argumentos. Bloquea para siempre (o hasta que el socket falle al
    cerrarse el proceso), así que quien la llame no debe esperar a que retorne."""
    ruta = _ruta_socket(base_dir)
    if ruta.exists():
        # Nadie más puede estar escuchando ahi si este proceso llegó a arrancar: launcher.py ya
        # comprobó hay_instancia_activa() antes de lanzarnos. Es un socket viejo, se limpia.
        ruta.unlink()

    servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    servidor.bind(str(ruta))
    servidor.listen(1)
    try:
        while True:
            conexion, _ = servidor.accept()
            with conexion:
                conexion.recv(64)
            al_recibir_ping()
    finally:
        servidor.close()
        try:
            ruta.unlink()
        except OSError:
            pass
