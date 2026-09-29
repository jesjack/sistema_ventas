from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStyleFactory

from . import dvr_log
from .main_window import MainWindow
from .shared_paths import (
    SHARE_RUNTIME_DIR,
    apply_shared_umask,
    ensure_shared_root,
    purge_old_ready_markers,
    ready_marker_path,
)
from .singleton_lock import acquire_singleton_lock

LOCK_PATH = SHARE_RUNTIME_DIR / "camera_viewer.lock"


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
/* Casillas: borde claro (con el predeterminado de Fusion el borde queda casi negro sobre el fondo
   oscuro y no se distinguen). Marcada = relleno azul; a medias (fila/columna con algunas) = azul oscuro. */
QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid #9CA3AF; border-radius: 3px;
    background-color: #0B1120;
}
QCheckBox::indicator:hover { border-color: #F3F4F6; }
QCheckBox::indicator:checked { background-color: #3B82F6; border-color: #BFDBFE; }
QCheckBox::indicator:indeterminate { background-color: #1E40AF; border-color: #BFDBFE; }
QCheckBox::indicator:disabled { border-color: #6B7280; background-color: #111827; }
QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled {
    background-color: #1E3A8A; border-color: #6B7280;
}
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
    apply_shared_umask()  # todo lo que este proceso cree en share/ queda escribible por el grupo
    ensure_shared_root(SHARE_RUNTIME_DIR)

    # Sin esto, cada clic en "VER CAMARAS" (p. ej. porque la ventana
    # anterior parecia congelada) lanza OTRO proceso completo, cada uno con
    # sus propias 4 conexiones RTSP al mismo DVR -- eso fue justo lo que se
    # vio en produccion (2 instancias huerfanas, 8 conexiones RTSP
    # concurrentes, el DVR sin poder servirlas todas). Ver singleton_lock.py.
    lock_file = acquire_singleton_lock(LOCK_PATH)
    if lock_file is None:
        print("camera_viewer ya está corriendo; no se abre una instancia nueva.")
        sys.exit(0)

    dvr_log.enable()  # tiempos de cada descarga y consulta al DVR, en share/logs/camera_viewer/run_*.log

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

    # Avisa a quien lanzó este proceso (ver_camaras.py) que la ventana ya se mostró, para que
    # deje de mostrar "Abriendo cámaras…" -- QTimer.singleShot(0, ...) para escribirlo ya
    # arrancado el bucle de eventos, no aquí: show() solo AGENDA que se muestre, el primer
    # dibujo real ocurre recién ahí. purge_old_ready_markers() de paso (nadie más los limpia:
    # esta app cierra con os._exit, sin oportunidad de borrar el suyo al terminar).
    purge_old_ready_markers()
    marker = ready_marker_path(os.getpid())

    def _avisar_ventana_lista() -> None:
        try:
            marker.touch(exist_ok=True)
        except OSError:
            pass  # no es crítico: quien espera este archivo igual tiene su propio tope de tiempo

    QTimer.singleShot(0, _avisar_ventana_lista)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
