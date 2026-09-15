from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QStyleFactory

from .main_window import MainWindow

LOCK_PATH = Path(__file__).resolve().parent.parent / "runtime" / "camera_viewer.lock"


def _acquire_singleton_lock(lock_path: Path):
    """Bloqueo de instancia unica: sin esto, cada clic en "VER CAMARAS"
    (p. ej. porque la ventana anterior parecia congelada) lanza OTRO
    proceso completo, cada uno con sus propias 4 conexiones RTSP al mismo
    DVR -- eso fue justo lo que se vio en produccion (2 instancias
    huerfanas, 8 conexiones RTSP concurrentes, el DVR sin poder servirlas
    todas). Usa un lock de archivo (flock/msvcrt) en vez de un PID file:
    el sistema operativo lo libera solo si el proceso muere de golpe (kill
    -9, crash), asi que nunca queda un lock "trabado" que haya que limpiar
    a mano. Devuelve el file handle (hay que mantenerlo abierto mientras
    viva el proceso) o None si ya hay otra instancia corriendo."""
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


# Paleta oscura de base -- se refinara mas adelante, esto es punto de
# partida funcional, no diseño final.
DARK_STYLESHEET = """
QWidget { background-color: #0F172A; color: #E5E7EB; font-size: 13px; }
QLineEdit {
    background-color: #111827; border: 1px solid #1F2937;
    padding: 4px 6px; border-radius: 3px;
}
QPushButton {
    background-color: #111827; border: 1px solid #1F2937;
    padding: 4px 6px; border-radius: 3px;
}
QPushButton:hover { background-color: #1F2937; }
QPushButton:pressed { background-color: #0B1120; }
QCalendarWidget QToolButton { color: #E5E7EB; background-color: #111827; }
QCalendarWidget QAbstractItemView {
    background-color: #0B1120; color: #E5E7EB;
    /* La fila de nombres de dia (dom/lun/.../sab) se pinta con el rol de
    paleta AlternateBase, no con el fondo normal -- sin esto queda blanca
    aunque el resto de la grilla ya este oscura. */
    alternate-background-color: #111827;
}
QCalendarWidget QWidget#qt_calendar_navigationbar { background-color: #111827; }
"""


def main() -> None:
    lock_file = _acquire_singleton_lock(LOCK_PATH)
    if lock_file is None:
        print("camera_viewer ya esta corriendo; no se abre una instancia nueva.")
        sys.exit(0)

    app = QApplication(sys.argv)
    # Fuerza Fusion en vez del tema nativo del sistema (p. ej. la
    # integracion GTK/GNOME): ese motor nativo pinta partes de widgets
    # compuestos como QCalendarWidget a su manera (bordes, celda por celda)
    # ignorando el CSS fino de mas abajo -- Fusion es el unico estilo de Qt
    # que garantiza respetar el stylesheet tal cual esta escrito.
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
