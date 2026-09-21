from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QPushButton, QWidget

# Un botón que a la vez es una barra de progreso: el relleno de color avanza por dentro del botón
# mientras el texto (p. ej. "Exportando… 37 %") sigue legible encima. Se usa para "Exportar" en el
# panel izquierdo: idle -> corriendo (azul) -> pausado (ámbar) -> listo (verde) / con error (rojo).

IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
DONE = "done"
ERROR = "error"

FILL_COLORS = {
    RUNNING: QColor(59, 130, 246, 120),
    PAUSED: QColor(245, 158, 11, 120),
    DONE: QColor(34, 197, 94, 120),
    ERROR: QColor(239, 68, 68, 120),
}


class ProgressButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._idle_text = text
        self._state = IDLE
        self._fraction = 0.0

    @property
    def state(self) -> str:
        return self._state

    @property
    def fraction(self) -> float:
        return self._fraction

    def set_state(self, state: str, text: str | None = None, fraction: float = 0.0, tooltip: str = "") -> None:
        self._state = state
        self._fraction = min(1.0, max(0.0, fraction)) if state != IDLE else 0.0
        self.setText(text if text is not None else self._idle_text)
        self.setToolTip(tooltip)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre de Qt)
        super().paintEvent(event)
        color = FILL_COLORS.get(self._state)
        if color is None or self._fraction <= 0:
            return
        painter = QPainter(self)
        painter.setPen(QColor(0, 0, 0, 0))
        painter.setBrush(color)
        inner = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(QRectF(inner.left(), inner.top(), inner.width() * self._fraction, inner.height()), 3, 3)
        painter.end()
