from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import icons
from .button_group import BUTTON_GAP, fuse_buttons

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
    avance de cada canal; al final, el resultado.

    `window_mode` es la variante de la ventana de guardado (clip_export_dialog.py):
    una sola fila (carpeta como campo de texto + "Examinar…", tamaño, Guardar,
    Cancelar; luego avance y resultado), sin marcas ni "Inicio del clip" (las asas de su
    línea de tiempo y sus controles ya lo hacen) y con las casillas de canal sueltas, para
    que la ventana las ponga sobre los paneles de cámara (`channel_check`).

    `compact` es la variante de la ventana principal (fila de controles, ver
    MainWindow): una sola fila de botones con Inicio y Fin como iconos (corchetes) y
    "Guardar clip…" fundidos en un grupo, más "Guardar últimos 30 s". Sin etiqueta de rango ni
    "Limpiar": las horas se rotulan sobre la línea de tiempo, y volver a marcar el inicio o el
    fin ya reajusta el rango."""

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
    folder_edited = Signal(str)  # el texto de la carpeta cambió (cada tecla)
    folder_committed = Signal(str)  # Enter o salir del campo

    def __init__(
        self, channels: tuple[int, ...], parent: QWidget | None = None, window_mode: bool = False, compact: bool = False
    ) -> None:
        super().__init__(parent)
        self._state = IDLE
        self._channels = channels
        self._window_mode = window_mode
        self._compact = compact
        self._available: set[int] | None = None  # None: aún no se sabe, todos disponibles
        self._checks_editable = True

        self._mark_start = QPushButton("[ Inicio")
        self._mark_end = QPushButton("Fin ]")
        if compact:
            for button, icon, tip in (
                (self._mark_start, icons.mark_start_icon(), "Marcar aquí el inicio del clip"),
                (self._mark_end, icons.mark_end_icon(), "Marcar aquí el fin del clip"),
            ):
                button.setText("")
                button.setIcon(icon)
                button.setIconSize(icons.ICON_SIZE)
                button.setToolTip(tip)
                button.setFixedWidth(46)
        self._range_label = QLabel()
        self._range_label.setStyleSheet("color: #9CA3AF;")
        self._clear = QPushButton("Limpiar")
        self._save = QPushButton("Guardar clip…")
        self._save_last = QPushButton("Guardar últimos 30 s")
        self._restart = QPushButton("Inicio del clip")
        self._folder_button = QPushButton()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Carpeta donde guardar los clips")
        self._folder_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # que no atrape la barra espaciadora al abrir
        self._folder_edit.setMinimumWidth(240)
        self._folder_edit.setFixedHeight(BUTTON_HEIGHT)
        self._browse = QPushButton("Examinar…")
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
            self._folder_button, self._browse, self._confirm, self._cancel_preview, self._cancel_export, self._open_folder, self._dismiss,
        ]
        for button in self._buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # que la barra espaciadora siga siendo pausa
            button.setAutoDefault(False)  # y que Enter en el campo de carpeta no pulse ninguno
            button.setFixedHeight(BUTTON_HEIGHT)

        self._mark_start.clicked.connect(self.mark_start_clicked)
        self._mark_end.clicked.connect(self.mark_end_clicked)
        self._clear.clicked.connect(self.clear_marks_clicked)
        self._save.clicked.connect(self.save_clicked)
        self._save_last.clicked.connect(self.save_last_clicked)
        self._restart.clicked.connect(self.restart_clicked)
        self._folder_button.clicked.connect(self.choose_folder_clicked)
        self._browse.clicked.connect(self._browse_clicked)
        self._folder_edit.textEdited.connect(self.folder_edited)
        self._folder_edit.editingFinished.connect(self._folder_finished)
        self._confirm.clicked.connect(self.confirm_clicked)
        self._cancel_preview.clicked.connect(self.cancel_preview_clicked)
        self._cancel_export.clicked.connect(self.cancel_export_clicked)
        self._open_folder.clicked.connect(self.open_folder_clicked)
        self._dismiss.clicked.connect(self.dismiss_clicked)

        if compact:
            row = QHBoxLayout(self)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(BUTTON_GAP)
            row.addWidget(fuse_buttons([self._mark_start, self._mark_end, self._save]))
            row.addWidget(self._save_last)
            self._top_widgets = ()
            self._bottom_widgets = (self._mark_start, self._mark_end, self._save, self._save_last)
        elif window_mode:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(self._folder_edit, 1)
            for widget in (self._browse, self._size_label, self._confirm, self._cancel_preview):
                row.addWidget(widget)
            row.addWidget(self._message, 1)
            for widget in (self._cancel_export, self._open_folder, self._dismiss):
                row.addWidget(widget)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addLayout(row)
            self.setMinimumHeight(BUTTON_HEIGHT)  # la fila no se encoge mientras no muestra nada
            self._top_widgets = ()
            self._bottom_widgets = (
                self._folder_edit, self._browse, self._size_label, self._confirm, self._cancel_preview,
                self._message, self._cancel_export, self._open_folder, self._dismiss,
            )
        else:
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
        if self._compact:
            show = {
                IDLE: {self._mark_start, self._mark_end, self._save, self._save_last},
                PREVIEW: set(),  # la vista previa y el guardado viven en su propia ventana
                EXPORTING: set(),
                FINISHED: set(),
            }[state]
        elif self._window_mode:
            show = {
                IDLE: set(),
                PREVIEW: {self._folder_edit, self._browse, self._size_label, self._confirm, self._cancel_preview},
                EXPORTING: set(),  # el avance y el resultado los muestra la ventana de avance
                FINISHED: set(),
            }[state]
        else:
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
        self._checks_editable = state == PREVIEW  # tras guardar (o durante) ya no se cambian los canales
        self._apply_checks()
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
        if not self._folder_edit.hasFocus():  # no pisar lo que se está escribiendo
            self._folder_edit.setText(str(folder))
            self.set_folder_valid(True)
        self._folder_edit.setToolTip(str(folder))
        self._size_label.setText(size_text)

    def set_folder_valid(self, valid: bool) -> None:
        """Marca en rojo el campo de carpeta mientras lo escrito no sirve."""
        self._folder_edit.setStyleSheet("" if valid else "QLineEdit { border: 1px solid #EF4444; border-radius: 3px; }")

    def _browse_clicked(self) -> None:
        self._folder_edit.clearFocus()  # el texto se refresca con la carpeta elegida
        self.choose_folder_clicked.emit()

    def _folder_finished(self) -> None:
        text = self._folder_edit.text()
        self._folder_edit.clearFocus()  # y la barra espaciadora vuelve a ser pausa
        self.folder_committed.emit(text)

    def set_message(self, text: str) -> None:
        self._message.setText(text)

    def selected_channels(self) -> list[int]:
        return [channel for channel, check in self._checks.items() if check.isChecked()]

    def set_available_channels(self, available: set[int]) -> None:
        """Canales con grabación en el rango: los demás se desmarcan y deshabilitan."""
        self._available = set(available)
        self._apply_checks()

    def _apply_checks(self) -> None:
        for channel, check in self._checks.items():
            has = self.channel_available(channel)
            check.setEnabled(has and self._checks_editable)
            if not has:
                check.setChecked(False)
            check.setToolTip("" if has else "Sin grabaciones en ese rango")

    def channel_available(self, channel: int) -> bool:
        return self._available is None or channel in self._available

    def channel_check(self, channel: int) -> QCheckBox:
        """La casilla de un canal (la ventana de guardado la pone sobre el panel de cámara)."""
        return self._checks[channel]

    def enable_confirm(self, enabled: bool) -> None:
        self._confirm.setEnabled(enabled)
