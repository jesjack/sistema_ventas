from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow

# Paleta oscura de base -- se refinara mas adelante, esto es punto de
# partida funcional, no diseño final.
DARK_STYLESHEET = """
QWidget { background-color: #0F172A; color: #E5E7EB; font-size: 13px; }
QLineEdit {
    background-color: #111827; border: 1px solid #1F2937;
    padding: 4px 6px; border-radius: 3px;
}
QCalendarWidget QToolButton { color: #E5E7EB; background-color: #111827; }
QCalendarWidget QAbstractItemView {
    background-color: #0B1120; color: #E5E7EB;
    selection-background-color: #2563EB; selection-color: white;
}
QCalendarWidget QWidget#qt_calendar_navigationbar { background-color: #111827; }
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
