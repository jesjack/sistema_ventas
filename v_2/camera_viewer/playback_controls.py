from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

JUMP_SECONDS = 10
# Velocidades que ofrece el botón, en orden de rotación. Solo las que el
# equipo sostiene: con los 4 canales el techo medido es ~x1.9 (x3 y x4 no
# pasan de ~x1.7-1.9), ver informes/REPRODUCCION_VELOCIDAD.md.
SPEEDS = (0.5, 1.0, 1.5, 2.0)


class PlaybackControls(QWidget):
    """Barra de controles de la vista de grabaciones: -10 s, pausa/reanudar,
    +10 s, avance de un cuadro (solo en pausa) y velocidad. Solo emite
    señales; quien decide qué hacer es MainWindow. Los botones no toman el
    foco, para que la barra espaciadora no los active por su cuenta."""

    pause_clicked = Signal()
    jump_clicked = Signal(int)
    step_clicked = Signal()
    speed_selected = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._speed = 1.0
        self._paused = False
        self._active = False

        self._back = QPushButton(f"⏪ {JUMP_SECONDS} s")
        self._pause = QPushButton("⏸ Pausa")
        self._forward = QPushButton(f"{JUMP_SECONDS} s ⏩")
        self._step = QPushButton("⏭ Cuadro")
        self._speed_button = QPushButton()
        self._buttons = (self._back, self._pause, self._forward, self._step, self._speed_button)
        for button in self._buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._back.clicked.connect(lambda: self.jump_clicked.emit(-JUMP_SECONDS))
        self._forward.clicked.connect(lambda: self.jump_clicked.emit(JUMP_SECONDS))
        self._pause.clicked.connect(self.pause_clicked)
        self._step.clicked.connect(self.step_clicked)
        self._speed_button.clicked.connect(self._cycle_speed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        for button in self._buttons:
            layout.addWidget(button)
        layout.addStretch(1)

        self.set_speed(1.0)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        """Habilita los controles (hay una reproducción en curso)."""
        self._active = active
        for button in self._buttons:
            button.setEnabled(active)
        self.set_paused(self._paused)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pause.setText("▶ Reanudar" if paused else "⏸ Pausa")
        self._step.setEnabled(self._active and paused)

    def set_speed(self, speed: float) -> None:
        self._speed = speed
        self._speed_button.setText(f"Velocidad x{speed:g}")

    def _cycle_speed(self) -> None:
        current = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - self._speed))
        self.speed_selected.emit(SPEEDS[(current + 1) % len(SPEEDS)])
