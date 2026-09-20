from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

BUTTON_HEIGHT = 30

# Estados de la barra
IDLE = "idle"  # marcar inicio/fin y elegir guardar
PREVIEW = "preview"  # viendo cómo quedaría el clip; confirmar o cancelar
EXPORTING = "exporting"  # descargando/guardando
FINISHED = "finished"  # resultado


class ExportBar(QWidget):
    """Barra de exportación de un clip corto, bajo los controles de reproducción.

    Solo emite señales y muestra estado; la lógica vive en MainWindow. Cuatro
    estados (ver arriba): en reposo se marcan el inicio y el fin y se elige
    guardar; en vista previa la reproducción queda acotada al rango y aquí se
    elige canales y carpeta y se confirma; durante la exportación muestra el
    avance de cada canal; al final, el resultado."""

    mark_start_clicked = Signal()
    mark_end_clicked = Signal()
    clear_marks_clicked = Signal()
    save_clicked = Signal()
    save_last_clicked = Signal()
    restart_clicked = Signal()
    confirm_clicked = Signal()
    cancel_preview_clicked = Signal()
    cancel_export_clicked = Signal()
    open_folder_clicked = Signal()
    choose_folder_clicked = Signal()
    dismiss_clicked = Signal()
    channels_changed = Signal()

    def __init__(self, channels: tuple[int, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = IDLE
        self._channels = channels

        self._mark_start = QPushButton("[ Inicio")
        self._mark_end = QPushButton("Fin ]")
        self._range_label = QLabel()
        self._range_label.setStyleSheet("color: #9CA3AF;")
        self._clear = QPushButton("Limpiar")
        self._save = QPushButton("Guardar clip…")
        self._save_last = QPushButton("Guardar últimos 30 s")
        self._restart = QPushButton("Inicio del clip")
        self._folder_button = QPushButton()
        self._size_label = QLabel()
        self._confirm = QPushButton("Guardar")
        self._cancel_preview = QPushButton("Cancelar")
        self._cancel_export = QPushButton("Cancelar exportación")
        self._open_folder = QPushButton("Abrir carpeta")
        self._dismiss = QPushButton("Cerrar")
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._checks = {channel: QCheckBox(f"CAM {channel}") for channel in channels}
        for check in self._checks.values():
            check.setChecked(True)
            check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            check.toggled.connect(lambda _checked: self.channels_changed.emit())

        self._buttons = [
            self._mark_start, self._mark_end, self._clear, self._save, self._save_last, self._restart,
            self._folder_button, self._confirm, self._cancel_preview, self._cancel_export, self._open_folder, self._dismiss,
        ]
        for button in self._buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # que la barra espaciadora siga siendo pausa
            button.setFixedHeight(BUTTON_HEIGHT)

        self._mark_start.clicked.connect(self.mark_start_clicked)
        self._mark_end.clicked.connect(self.mark_end_clicked)
        self._clear.clicked.connect(self.clear_marks_clicked)
        self._save.clicked.connect(self.save_clicked)
        self._save_last.clicked.connect(self.save_last_clicked)
        self._restart.clicked.connect(self.restart_clicked)
        self._folder_button.clicked.connect(self.choose_folder_clicked)
        self._confirm.clicked.connect(self.confirm_clicked)
        self._cancel_preview.clicked.connect(self.cancel_preview_clicked)
        self._cancel_export.clicked.connect(self.cancel_export_clicked)
        self._open_folder.clicked.connect(self.open_folder_clicked)
        self._dismiss.clicked.connect(self.dismiss_clicked)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch(1)
        for widget in (self._mark_start, self._mark_end, self._range_label, self._clear, self._restart, self._save, self._save_last):
            top.addWidget(widget)
        top.addStretch(1)
        self._top = top

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addStretch(1)
        for check in self._checks.values():
            bottom.addWidget(check)
        for widget in (self._folder_button, self._size_label, self._confirm, self._cancel_preview, self._message, self._cancel_export, self._open_folder, self._dismiss):
            bottom.addWidget(widget)
        bottom.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addLayout(bottom)

        self._top_widgets = (self._mark_start, self._mark_end, self._range_label, self._clear, self._restart, self._save, self._save_last)
        self._bottom_widgets = (
            *self._checks.values(), self._folder_button, self._size_label, self._confirm, self._cancel_preview,
            self._message, self._cancel_export, self._open_folder, self._dismiss,
        )
        self.set_active(False)
        self.set_state(IDLE)

    # -- estado ---------------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        self._state = state
        show = {
            IDLE: {self._mark_start, self._mark_end, self._range_label, self._clear, self._save, self._save_last},
            PREVIEW: {
                self._mark_start, self._mark_end, self._range_label, self._restart,
                *self._checks.values(), self._folder_button, self._size_label, self._confirm, self._cancel_preview,
            },
            EXPORTING: {self._range_label, self._message, self._cancel_export},
            FINISHED: {self._range_label, self._message, self._open_folder, self._dismiss},
        }[state]
        for widget in (*self._top_widgets, *self._bottom_widgets):
            widget.setVisible(widget in show)
        self._refresh_enabled()

    def set_active(self, active: bool) -> None:
        """Hay una reproducción en curso: solo entonces se pueden marcar y guardar clips."""
        self._active = active
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        active = getattr(self, "_active", False)
        for button in (self._mark_start, self._mark_end, self._save_last):
            button.setEnabled(active)
        self._clear.setEnabled(active and self._has_marks)
        self._save.setEnabled(active and self._has_marks)
        self._restart.setEnabled(True)

    _has_marks = False

    def set_marks(self, has_marks: bool, range_text: str) -> None:
        self._has_marks = has_marks
        self._range_label.setText(range_text)
        self._refresh_enabled()

    def set_preview_info(self, folder: Path, size_text: str) -> None:
        self._folder_button.setText(f"Carpeta: {folder}")
        self._folder_button.setToolTip(str(folder))
        self._size_label.setText(size_text)

    def set_message(self, text: str) -> None:
        self._message.setText(text)

    def selected_channels(self) -> list[int]:
        return [channel for channel, check in self._checks.items() if check.isChecked()]

    def set_available_channels(self, available: set[int]) -> None:
        """Canales con grabación en el rango: los demás se desmarcan y deshabilitan."""
        for channel, check in self._checks.items():
            has = channel in available
            check.setEnabled(has)
            if not has:
                check.setChecked(False)
            check.setToolTip("" if has else "Sin grabaciones en ese rango")

    def enable_confirm(self, enabled: bool) -> None:
        self._confirm.setEnabled(enabled)
