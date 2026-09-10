from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCalendarWidget, QSizePolicy, QVBoxLayout, QWidget

# Compacto y cuadrado a proposito -- el espacio que libera se usa para el
# panel de conexion (ver ConnectionPanel) en la misma columna.
MAX_SIZE = 260


class CalendarPanel(QWidget):
    """Calendario real (grilla de dias, navegacion por mes) para elegir el
    dia a consultar -- no un input de texto con forma de fecha."""

    day_selected = Signal(date)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._calendar = QCalendarWidget(self)
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setMaximumDate(date.today())
        self._calendar.setMaximumSize(MAX_SIZE, MAX_SIZE)
        self._calendar.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self._calendar.clicked.connect(self._on_selected)
        self._calendar.activated.connect(self._on_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._calendar)

    def _on_selected(self, qdate) -> None:
        self.day_selected.emit(qdate.toPython())

    def selected_date(self) -> date:
        return self._calendar.selectedDate().toPython()
