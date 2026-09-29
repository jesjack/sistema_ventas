"""Punto de entrada: python -m admin_botones <base_dir>.

`base_dir` es la carpeta raíz del proyecto (donde vive .venv/, ventas.db,
etc.) -- la misma que ya recibe camera_viewer, pasada explícitamente porque
este proceso arranca con su propio cwd (ver admin_botones/launcher.py) y no
debe adivinar dónde está el proyecto."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication

from services.botones_service import BotonesService
from services.usuarios_service import UsuariosService

from admin_botones.instancia_unica import escuchar
from admin_botones.ventana_botones import VentanaBotones


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python -m admin_botones <base_dir>", file=sys.stderr)
        return 1

    # base_dir SÍ se usa aquí (a diferencia de ventas.db, resuelto por su propia ruta por
    # defecto): es donde vive el socket de instancia única (ver instancia_unica.py), que necesita
    # una ruta compartida y estable entre el proceso que lanza y el que ya está corriendo.
    base_dir = Path(sys.argv[1])

    app = QApplication(sys.argv)
    ventana = VentanaBotones(BotonesService(), UsuariosService())

    # Hilo aparte, daemon: si un segundo clic en "ADMINISTRAR ADMINS" nos manda un ping (ver
    # launcher.py:launch_detached), traemos esta ventana al frente en vez de que se abra otra.
    # .emit() es seguro de llamar desde un hilo que no es el principal -- Qt lo encola hacia el
    # hilo de la ventana en vez de tocar la UI directo desde aquí.
    hilo_escucha = threading.Thread(
        target=escuchar, args=(base_dir, ventana.solicitar_traer_al_frente.emit), daemon=True,
    )
    hilo_escucha.start()

    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
