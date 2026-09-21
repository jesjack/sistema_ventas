from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from . import icons
from .button_group import BUTTON_GAP, fuse_buttons

JUMP_SECONDS = 10
# Velocidades que ofrece el botón, en orden de rotación. Solo las que el
# equipo sostiene: con los 4 canales el techo medido es ~x1.9 (x3 y x4 no
# pasan de ~x1.7-1.9), ver informes/REPRODUCCION_VELOCIDAD.md.
SPEEDS = (0.5, 1.0, 1.5, 2.0)
NORMAL_SPEED = 1.0
BUTTON_HEIGHT = 30  # todos igual: el texto con emojis pedía más alto que el resto
DIRECTION_STYLE = "QPushButton:checked { background-color: #1D4ED8; border-color: #3B82F6; color: #FFFFFF; }"


class PlaybackControls(QWidget):
    """Barra de controles de la vista de grabaciones: -10 s, pausa/reanudar
    (un icono que cambia), +10 s, reversa (un icono que se enciende mientras se
    reproduce hacia atrás) y velocidad (más lento, la velocidad actual -que al
    pulsarla vuelve a x1- y más rápido, fundidos en un solo botón). Solo emite
    señales; quien decide qué hacer es MainWindow. Los botones no toman el foco,
    para que la barra espaciadora no los active por su cuenta. `set_trailing_widget`
    deja sitio al final de la fila (MainWindow pone ahí las marcas del clip)."""

    pause_clicked = Signal()
    jump_clicked = Signal(int)
    reverse_toggled = Signal(bool)
    speed_selected = Signal(float)
    restart_clicked = Signal()  # solo con `with_restart`

    def __init__(self, parent: QWidget | None = None, with_restart: bool = False) -> None:
        super().__init__(parent)
        self._speed = NORMAL_SPEED
        self._paused = False
        self._reverse = False
        self._active = False

        self._back = QPushButton(f"−{JUMP_SECONDS} s")
        self._pause = QPushButton()
        self._pause_icon, self._play_icon = icons.pause_icon(), icons.play_icon()
        self._forward = QPushButton(f"+{JUMP_SECONDS} s")
        self._direction = QPushButton()
        self._direction.setIcon(icons.reverse_icon())
        self._direction.setCheckable(True)
        self._direction.setStyleSheet(DIRECTION_STYLE)
        self._slower = QPushButton("−")
        self._speed_button = QPushButton()  # muestra la velocidad; al pulsarla vuelve a x1
        self._faster = QPushButton("+")
        self._restart = QPushButton("Inicio del clip") if with_restart else None  # ventana de guardado
        self._buttons = (self._back, self._pause, self._forward, self._direction, self._slower, self._speed_button, self._faster)
        if self._restart is not None:
            self._buttons += (self._restart,)
        for button in self._buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedHeight(BUTTON_HEIGHT)
        for button in (self._slower, self._faster):
            button.setFixedWidth(BUTTON_HEIGHT)
        self._speed_button.setMinimumWidth(54)
        for button in (self._pause, self._direction):
            button.setIconSize(icons.ICON_SIZE)
            button.setFixedWidth(46)

        self._back.clicked.connect(lambda: self.jump_clicked.emit(-JUMP_SECONDS))
        self._forward.clicked.connect(lambda: self.jump_clicked.emit(JUMP_SECONDS))
        self._pause.clicked.connect(self.pause_clicked)
        self._direction.clicked.connect(lambda checked: self.reverse_toggled.emit(checked))
        self._slower.clicked.connect(lambda: self._shift_speed(-1))
        self._faster.clicked.connect(lambda: self._shift_speed(+1))
        self._speed_button.clicked.connect(lambda: self.speed_selected.emit(NORMAL_SPEED))
        if self._restart is not None:
            self._restart.clicked.connect(self.restart_clicked)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(BUTTON_GAP)  # el mismo hueco entre todos los botones y grupos de la fila
        layout.addStretch(1)
        for widget in (self._back, self._pause, self._forward):
            layout.addWidget(widget)
        layout.addWidget(self._direction)
        layout.addWidget(fuse_buttons([self._slower, self._speed_button, self._faster]))
        if self._restart is not None:
            layout.addWidget(self._restart)
        self._trailing = QHBoxLayout()
        self._trailing.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._trailing)
        layout.addStretch(1)

        self.set_speed(NORMAL_SPEED)
        self.set_active(False)

    def set_trailing_widget(self, widget: QWidget) -> None:
        """Un widget más al final de la fila (con el mismo hueco que entre los demás botones)."""
        self._trailing.addWidget(widget)

    def set_active(self, active: bool) -> None:
        """Habilita los controles (hay una reproducción en curso)."""
        self._active = active
        for button in self._buttons:
            button.setEnabled(active)
        self.set_paused(self._paused)
        self.set_reverse(self._reverse)
        self.set_speed(self._speed)

    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._pause.setIcon(self._play_icon if paused else self._pause_icon)
        self._pause.setToolTip("Reanudar" if paused else "Pausar")

    def set_reverse(self, reverse: bool) -> None:
        self._reverse = reverse
        self._direction.setChecked(reverse)  # encendido = reproduciendo hacia atrás
        self._direction.setToolTip("Reproduciendo en reversa (clic para volver al sentido normal)" if reverse else "Reproducir en reversa")

    def set_speed(self, speed: float) -> None:
        self._speed = speed
        self._speed_button.setText(f"x{speed:g}")
        index = self._speed_index()
        self._slower.setEnabled(self._active and index > 0)
        self._faster.setEnabled(self._active and index < len(SPEEDS) - 1)
        self._speed_button.setEnabled(self._active and speed != NORMAL_SPEED)  # en x1 no hay nada que restaurar

    def _speed_index(self) -> int:
        return min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - self._speed))

    def _shift_speed(self, direction: int) -> None:
        index = self._speed_index() + direction
        if 0 <= index < len(SPEEDS):
            self.speed_selected.emit(SPEEDS[index])
