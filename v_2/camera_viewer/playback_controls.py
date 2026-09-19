from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

JUMP_SECONDS = 10
# Velocidades que ofrece el botón, en orden de rotación. Solo las que el
# equipo sostiene: con los 4 canales el techo medido es ~x1.9 (x3 y x4 no
# pasan de ~x1.7-1.9), ver informes/REPRODUCCION_VELOCIDAD.md.
SPEEDS = (0.5, 1.0, 1.5, 2.0)


BUTTON_HEIGHT = 30  # todos igual: el texto con emojis pedía más alto que el resto


class PlaybackControls(QWidget):
    """Barra de controles de la vista de grabaciones: -10 s, pausa/reanudar,
    +10 s, avance de un cuadro (solo en pausa) y velocidad (más lento / más
    rápido). Solo emite señales; quien decide qué hacer es MainWindow. Los
    botones no toman el foco, para que la barra espaciadora no los active por
    su cuenta."""

    pause_clicked = Signal()
    jump_clicked = Signal(int)
    step_clicked = Signal()
    speed_selected = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._speed = 1.0
        self._paused = False
        self._active = False

        self._back = QPushButton(f"−{JUMP_SECONDS} s")
        self._pause = QPushButton("Pausa")
        self._forward = QPushButton(f"+{JUMP_SECONDS} s")
        self._step = QPushButton("Cuadro")
        self._slower = QPushButton("−")
        self._faster = QPushButton("+")
        self._speed_label = QLabel()
        self._speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._speed_label.setMinimumWidth(54)
        self._buttons = (self._back, self._pause, self._forward, self._step, self._slower, self._faster)
        for button in self._buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedHeight(BUTTON_HEIGHT)
        for button in (self._slower, self._faster):
            button.setFixedWidth(BUTTON_HEIGHT)
        self._speed_label.setFixedHeight(BUTTON_HEIGHT)
        self._pause.setMinimumWidth(96)  # cabe "Reanudar" sin que la barra cambie de ancho

        self._back.clicked.connect(lambda: self.jump_clicked.emit(-JUMP_SECONDS))
        self._forward.clicked.connect(lambda: self.jump_clicked.emit(JUMP_SECONDS))
        self._pause.clicked.connect(self.pause_clicked)
        self._step.clicked.connect(self.step_clicked)
        self._slower.clicked.connect(lambda: self._shift_speed(-1))
        self._faster.clicked.connect(lambda: self._shift_speed(+1))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        for widget in (self._back, self._pause, self._forward, self._step):
            layout.addWidget(widget)
        layout.addSpacing(16)
        for widget in (self._slower, self._speed_label, self._faster):
            layout.addWidget(widget)
        layout.addStretch(1)

        self.set_speed(1.0)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        """Habilita los controles (hay una reproducción en curso)."""
        self._active = active
        for button in self._buttons:
            button.setEnabled(active)
        self.set_paused(self._paused)
        self.set_speed(self._speed)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pause.setText("Reanudar" if paused else "Pausa")
        self._step.setEnabled(self._active and paused)

    def set_speed(self, speed: float) -> None:
        self._speed = speed
        self._speed_label.setText(f"x{speed:g}")
        index = self._speed_index()
        self._slower.setEnabled(self._active and index > 0)
        self._faster.setEnabled(self._active and index < len(SPEEDS) - 1)

    def _speed_index(self) -> int:
        return min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - self._speed))

    def _shift_speed(self, direction: int) -> None:
        index = self._speed_index() + direction
        if 0 <= index < len(SPEEDS):
            self.speed_selected.emit(SPEEDS[index])
