from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .export_clip import format_size, free_bytes_for, parse_folder
from .export_hours import PHASE_DOWNLOADING, PHASE_GAPS, PHASE_JOINING, HoursSpec, hour_has_recording, plan
from .hours_progress import PHASE_CANCELLED, PHASE_DONE, PHASE_QUEUED, HoursProgress
from .save_progress_dialog import (
    CARD_STYLE,
    COLOR_ACTIVE,
    COLOR_ERROR,
    COLOR_IDLE,
    COLOR_OK,
    COLOR_WARN,
    MUTED,
    ask_cancel,
    bar_style,
    format_clock,
)

# Las dos ventanas de "Exportar horas": la de selección (qué horas de qué canales y a qué carpeta, con
# el tamaño, el espacio libre y el tiempo estimados) y el panel de avance (no modal: la exportación
# dura de minutos a horas y la app sigue usándose). La lógica vive en export_hours.py y
# hours_controller.py; aquí solo se dibuja y se avisa con señales.

HOURS = range(24)
DEFAULT_CHANNELS = (1, 2, 3, 4)
THROUGHPUT_BYTES_PER_S = 6_000_000  # medido: ≈ 9 MB/s de un solo flujo; con la pausa entre trozos y la conversión, ≈ 6
GB = 1024 ** 3
INVALID_FOLDER_STYLE = "QLineEdit { border: 1px solid #EF4444; border-radius: 3px; }"


class _HeaderCheck(QCheckBox):
    """Casilla de una fila o columna entera: tres estados que solo cambia el programa (ninguna,
    algunas o todas las casillas de esa fila/columna), no el clic."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setTristate(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def nextCheckState(self) -> None:  # noqa: N802 (nombre de Qt)
        pass


class HoursSelectDialog(QDialog):
    def __init__(
        self,
        day: date,
        clips_by_channel: dict[int, list],
        now: datetime,
        folder: Path,
        parent: QWidget | None = None,
        free_bytes: Callable[[Path], int] = free_bytes_for,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Exportar horas — {day:%d/%m/%Y}")
        self._day, self._clips, self._now = day, clips_by_channel, now
        self._free_bytes = free_bytes
        self._folder = folder
        self._folder_ok = True
        self.channels = tuple(sorted(clips_by_channel)) or DEFAULT_CHANNELS
        self.cells: dict[tuple[int, int], QCheckBox] = {}
        self.hour_checks: dict[int, _HeaderCheck] = {}
        self.channel_checks: dict[int, _HeaderCheck] = {}

        intro = QLabel(
            "Elige las horas de cada canal. Se guarda un archivo por canal con las horas elegidas una tras otra; "
            "donde no haya grabación se rellena con un tramo negro que lo indica."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(MUTED)

        channel_row = QHBoxLayout()
        channel_row.addWidget(QLabel("Canales:"))
        for channel in self.channels:
            check = _HeaderCheck(f"CAM {channel}")
            check.clicked.connect(lambda _c=False, ch=channel: self._toggle_channel(ch))
            self.channel_checks[channel] = check
            channel_row.addWidget(check)
        channel_row.addStretch(1)
        self._all = QPushButton("Todo el día")
        self._none = QPushButton("Ninguna")
        for button in (self._all, self._none):
            button.setAutoDefault(False)
            channel_row.addWidget(button)
        self._all.clicked.connect(lambda: self._set_all(True))
        self._none.clicked.connect(lambda: self._set_all(False))

        blocks = QHBoxLayout()
        blocks.setSpacing(28)
        for first in (0, 12):
            blocks.addLayout(self._build_block(range(first, first + 12)))

        self._folder_edit = QLineEdit(str(folder))
        self._folder_edit.setMinimumWidth(320)
        self._folder_edit.textEdited.connect(self._folder_edited)
        browse = QPushButton("Examinar…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Carpeta:"))
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(browse)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._export = QPushButton("Exportar")
        self._export.setDefault(True)
        cancel = QPushButton("Cancelar")
        cancel.setAutoDefault(False)
        self._export.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._export)
        buttons.addWidget(cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(channel_row)
        layout.addLayout(blocks)
        layout.addLayout(folder_row)
        layout.addWidget(self._summary)
        layout.addLayout(buttons)
        self._refresh()

    # -- rejilla ---------------------------------------------------------------------------------------

    def _build_block(self, hours: range) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        grid.addWidget(QLabel("Hora"), 0, 0)
        for column, channel in enumerate(self.channels, start=1):
            label = QLabel(f"CAM {channel}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(MUTED)
            grid.addWidget(label, 0, column)
        for row, hour in enumerate(hours, start=1):
            header = _HeaderCheck(f"{hour:02d}:00")
            header.clicked.connect(lambda _c=False, h=hour: self._toggle_hour(h))
            self.hour_checks[hour] = header
            grid.addWidget(header, row, 0)
            for column, channel in enumerate(self.channels, start=1):
                check = QCheckBox()
                check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                recorded = hour_has_recording(self._clips.get(channel, []), self._day, hour, self._now)
                check.setEnabled(recorded)
                if not recorded:
                    check.setToolTip("Sin grabación en esta hora")
                check.toggled.connect(lambda _checked: self._refresh())
                self.cells[(channel, hour)] = check
                grid.addWidget(check, row, column, Qt.AlignmentFlag.AlignCenter)
        return grid

    def _enabled_cells(self, cells: list[tuple[int, int]]) -> list[QCheckBox]:
        return [self.cells[key] for key in cells if self.cells[key].isEnabled()]

    def _toggle_hour(self, hour: int) -> None:
        cells = self._enabled_cells([(channel, hour) for channel in self.channels])
        self._apply(cells, not all(cell.isChecked() for cell in cells))

    def _toggle_channel(self, channel: int) -> None:
        cells = self._enabled_cells([(channel, hour) for hour in HOURS])
        self._apply(cells, not all(cell.isChecked() for cell in cells))

    def _set_all(self, checked: bool) -> None:
        self._apply(self._enabled_cells(list(self.cells)), checked)

    def _apply(self, cells: list[QCheckBox], checked: bool) -> None:
        for cell in cells:
            cell.blockSignals(True)
            cell.setChecked(checked)
            cell.blockSignals(False)
        self._refresh()

    # -- carpeta ---------------------------------------------------------------------------------------

    def _folder_edited(self, text: str) -> None:
        path = parse_folder(text)
        self._folder_ok = path is not None
        if path is not None:
            self._folder = path
        self._folder_edit.setStyleSheet("" if self._folder_ok else INVALID_FOLDER_STYLE)
        self._refresh()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar las exportaciones", str(self._folder))
        if chosen:
            self._folder = Path(chosen)
            self._folder_ok = True
            self._folder_edit.setText(chosen)
            self._folder_edit.setStyleSheet("")
            self._refresh()

    # -- resultado y resumen ------------------------------------------------------------------------------

    def selection(self) -> dict[int, list[int]]:
        return {
            channel: [hour for hour in HOURS if self.cells[(channel, hour)].isChecked()]
            for channel in self.channels
            if any(self.cells[(channel, hour)].isChecked() for hour in HOURS)
        }

    def folder(self) -> Path:
        return self._folder

    def spec(self) -> HoursSpec:
        return HoursSpec(self._day, self.selection(), self._folder, self._clips, self._now)

    def estimate(self) -> tuple[float, float, float, int]:
        """(bytes totales, bytes que hay que tener libres, segundos de video, canales)."""
        plans = plan(self.spec())
        total = sum(item.estimated_bytes for item in plans)
        biggest = max((item.estimated_bytes for item in plans), default=0.0)  # el canal en curso guarda sus trozos y luego el MP4
        return total, total + biggest, sum(item.video_seconds for item in plans), len(plans)

    def _refresh(self) -> None:
        for channel, check in self.channel_checks.items():
            self._set_header(check, [self.cells[(channel, hour)] for hour in HOURS])
        for hour, check in self.hour_checks.items():
            self._set_header(check, [self.cells[(channel, hour)] for channel in self.channels])
        total, needed, video_seconds, channels = self.estimate()
        free = self._free_bytes(self._folder)
        problem = None
        if not self._folder_ok:
            problem = "La carpeta no es válida."
        elif channels == 0:
            problem = "Elige al menos una hora."
        elif needed > free:
            problem = f"No cabe: hacen falta ≈ {format_size(needed)} libres (con los archivos temporales) y hay {format_size(free)}."
        if problem:
            self._summary.setStyleSheet(f"color: {COLOR_ERROR};" if channels else MUTED)
            self._summary.setText(problem)
        else:
            self._summary.setStyleSheet(MUTED)
            hours_text = f"{video_seconds / 3600:.1f} h de video"
            self._summary.setText(
                f"{channels} canal{'es' if channels != 1 else ''} · {hours_text} · ≈ {format_size(total)} · "
                f"libre en disco: {format_size(free)} · tardaría ≈ {format_clock(total / THROUGHPUT_BYTES_PER_S)} "
                "si el DVR no se usa en otra cosa (la reproducción y los clips cortos tienen prioridad)."
            )
        self._export.setEnabled(problem is None)

    @staticmethod
    def _set_header(check: _HeaderCheck, cells: list[QCheckBox]) -> None:
        enabled = [cell for cell in cells if cell.isEnabled()]
        checked = sum(1 for cell in enabled if cell.isChecked())
        check.setEnabled(bool(enabled))
        if not enabled or checked == 0:
            check.setCheckState(Qt.CheckState.Unchecked)
        elif checked == len(enabled):
            check.setCheckState(Qt.CheckState.Checked)
        else:
            check.setCheckState(Qt.CheckState.PartiallyChecked)


# -- panel de avance -------------------------------------------------------------------------------------

REFRESH_MS = 300


class HoursChannelCard(QFrame):
    def __init__(self, channel: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.setObjectName("card")
        self.setStyleSheet(CARD_STYLE)
        self._icon = QLabel("●")
        self._icon.setFixedWidth(18)
        title = QLabel(f"CAM {channel}")
        title.setStyleSheet("font-weight: bold;")
        self._hours = QLabel()
        self._hours.setStyleSheet(MUTED)
        self._phase = QLabel()
        self._phase.setStyleSheet("font-weight: bold;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(MUTED)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._warnings = QLabel()
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet("color: #FBBF24;")

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._icon)
        head.addWidget(title)
        head.addWidget(self._hours)
        head.addStretch(1)
        head.addWidget(self._phase)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self._bar)
        layout.addWidget(self._detail)
        layout.addWidget(self._warnings)

    def refresh(self, progress: HoursProgress) -> None:
        item = progress.channel(self.channel)
        fraction = progress.fraction(self.channel)
        color, glyph, headline, detail = COLOR_IDLE, "●", "En cola", "Espera a que terminen los canales anteriores."
        self._hours.setText(f"· {progress.hours_text(self.channel)}")
        if item.phase == PHASE_QUEUED:
            self._set_bar(0, "En cola")
        elif item.phase == PHASE_DOWNLOADING:
            color, headline = COLOR_ACTIVE, "Descargando del DVR"
            self._set_bar(int(fraction * 1000), f"{int(fraction * 100)} %")
            piece = progress.piece_text(self.channel)
            detail = f"Trozo de las {piece}" if piece else "Preparando…"
            if progress.paused:
                color, headline, detail = COLOR_WARN, "En pausa", "Hay una vista en vivo abierta; sigue sola al cerrarla."
        elif item.phase == PHASE_GAPS:
            color, headline = COLOR_ACTIVE, "Preparando tramos sin grabación"
            self._set_bar(int(fraction * 1000), f"{int(fraction * 100)} %")
            detail = "Se generan los tramos negros con el aviso y la hora."
        elif item.phase == PHASE_JOINING:
            color, headline = COLOR_ACTIVE, "Uniendo en un solo archivo"
            self._set_bar(int(fraction * 1000), "Uniendo…")
            detail = "Se juntan los trozos sin recodificar y se verifica el archivo."
        elif item.phase == PHASE_DONE:
            color, glyph, headline = COLOR_OK, "✔", "Guardado"
            self._set_bar(1000, "100 %")
            name = item.result_path.rsplit("/", 1)[-1] if item.result_path else ""
            size = f" · {format_size(item.result_size)}" if item.result_size else ""
            detail = f"{name}{size}"
            if item.note:
                detail += f"\nⓘ {item.note}"
        elif item.phase == PHASE_CANCELLED:
            color, glyph, headline, detail = COLOR_WARN, "■", "Cancelado", "Este canal no se guardó."
            self._bar.setFormat("Cancelado")
        else:
            color, glyph, headline, detail = COLOR_ERROR, "✘", "No se pudo guardar", item.error or ""
            self._bar.setFormat("Falló")
        self._icon.setText(glyph)
        self._icon.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._phase.setText(headline)
        self._phase.setStyleSheet(f"font-weight: bold; color: {color};")
        self._bar.setStyleSheet(bar_style(color))
        self._detail.setText(detail)
        self._detail.setMinimumHeight(self._detail.fontMetrics().lineSpacing() * (detail.count("\n") + 1))
        warnings = item.warnings[-3:]
        extra = len(item.warnings) - len(warnings)
        text = "\n".join(f"⚠ {text}" for text in warnings) + (f"\n… y {extra} avisos más" if extra > 0 else "")
        self._warnings.setText(text)
        self._warnings.setMinimumHeight(self._warnings.fontMetrics().lineSpacing() * (text.count("\n") + 1) if warnings else 0)
        self._warnings.setVisible(bool(warnings))

    def _set_bar(self, value: int, text: str) -> None:
        self._bar.setValue(value)
        self._bar.setFormat(text)


class HoursProgressDialog(QDialog):
    """Panel de avance de la exportación de horas: no modal, minimizable; cerrarlo mientras se exporta solo
    lo oculta (se vuelve a abrir con el botón "Exportar"); Cancelar pide confirmación."""

    cancel_requested = Signal()
    open_folder_requested = Signal()
    dismissed = Signal()  # se cerró con la exportación ya terminada

    def __init__(
        self,
        progress: HoursProgress,
        parent: QWidget | None = None,
        confirm_cancel: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportando horas")
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setMinimumWidth(680)
        self._progress = progress
        self._confirm_cancel = confirm_cancel or (lambda downloaded: ask_cancel(self, downloaded))
        self._settled = False

        self._headline = QLabel()
        self._headline.setStyleSheet("font-size: 15pt; font-weight: bold;")
        spec = progress.spec
        total_hours = sum(len(hours) for hours in spec.cells.values())
        subtitle = QLabel(f"{spec.day:%d/%m/%Y} · {len(progress.channels)} canal{'es' if len(progress.channels) != 1 else ''} · {total_hours} horas-canal")
        subtitle.setStyleSheet(MUTED)
        folder = QLabel(f"Carpeta: {progress.folder}")
        folder.setStyleSheet(MUTED)
        folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder.setWordWrap(True)
        self._overall = QProgressBar()
        self._overall.setRange(0, 1000)
        self._overall.setStyleSheet(bar_style(COLOR_ACTIVE) + " QProgressBar { min-height: 22px; font-weight: bold; }")
        self._overall_text = QLabel()
        self._overall_text.setStyleSheet(MUTED)
        self._pause_note = QLabel("En pausa: hay una vista en vivo abierta. La exportación sigue sola cuando la cierres.")
        self._pause_note.setStyleSheet(f"color: {COLOR_WARN}; font-weight: bold;")
        self._pause_note.setWordWrap(True)

        self.cards: dict[int, HoursChannelCard] = {}
        cards_layout = QVBoxLayout()
        cards_layout.setSpacing(8)
        for channel in progress.channels:
            card = HoursChannelCard(channel)
            self.cards[channel] = card
            cards_layout.addWidget(card)

        self._cancel = QPushButton("Cancelar exportación")
        self._open_folder = QPushButton("Abrir carpeta")
        self._close = QPushButton("Cerrar")
        for button in (self._cancel, self._open_folder, self._close):
            button.setAutoDefault(False)
            button.setMinimumHeight(32)
            button.setMinimumWidth(120)
        self._cancel.clicked.connect(self._on_cancel)
        self._open_folder.clicked.connect(self.open_folder_requested)
        self._close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for button in (self._cancel, self._open_folder, self._close):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(self._headline)
        layout.addWidget(subtitle)
        layout.addWidget(folder)
        layout.addSpacing(6)
        layout.addWidget(self._overall)
        layout.addWidget(self._overall_text)
        layout.addWidget(self._pause_note)
        layout.addSpacing(6)
        layout.addLayout(cards_layout)
        layout.addSpacing(8)
        layout.addLayout(buttons)

        progress.changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        progress = self._progress
        for card in self.cards.values():
            card.refresh(progress)
        fraction = 1.0 if progress.finished else progress.overall_fraction()
        self._overall.setValue(int(fraction * 1000))
        self._overall.setFormat(f"{int(fraction * 100)} %")
        if progress.finished:
            self._show_result()
            return
        parts = [f"Transcurrido {format_clock(progress.elapsed())}"]
        eta = progress.overall_eta()
        if eta is not None:
            parts.append(f"quedan ≈ {format_clock(eta)}")
        speed = progress.speed()
        if speed is not None:
            parts.append("sin datos del DVR" if speed <= 0 else f"{format_size(speed)}/s")
        self._overall_text.setText(" · ".join(parts))
        self._fit()
        self._headline.setText("Cancelando…" if progress.cancelling else "En pausa" if progress.paused else "Exportando horas")
        self._pause_note.setVisible(progress.paused)
        self._cancel.setVisible(True)
        self._cancel.setEnabled(not progress.cancelling)
        self._cancel.setText("Cancelando…" if progress.cancelling else "Cancelar exportación")
        self._open_folder.setVisible(False)

    def _fit(self) -> None:
        """Las etiquetas con ajuste de línea (avisos, detalles) no piden su alto extra al layout: si el
        contenido ya no cabe, se agranda la ventana."""
        if self.sizeHint().height() > self.height():
            self.resize(self.width(), self.sizeHint().height())

    def _show_result(self) -> None:
        if self._settled:
            return
        self._settled = True
        self._timer.stop()
        progress = self._progress
        saved, total = progress.saved_count(), progress.total_count()
        if saved == total:
            headline, color = "Listo: se exportaron las horas", COLOR_OK
        elif saved == 0:
            headline, color = ("Cancelado", COLOR_WARN) if progress.was_cancelled() else ("No se pudo exportar", COLOR_ERROR)
        elif progress.was_cancelled():
            headline, color = f"Cancelado: se guardaron {saved} de {total} canales", COLOR_WARN
        else:
            headline, color = f"Se guardaron {saved} de {total} canales", COLOR_WARN
        self._headline.setText(headline)
        self._headline.setStyleSheet(f"font-size: 15pt; font-weight: bold; color: {color};")
        self._overall.setStyleSheet(bar_style(color) + " QProgressBar { min-height: 22px; font-weight: bold; }")
        if saved < total:
            self._overall.setValue(int(1000 * saved / total))
            self._overall.setFormat(f"{saved} de {total} canales guardados")
        self._overall_text.setText(f"Tardó {format_clock(progress.elapsed())}")
        self._pause_note.setVisible(False)
        self._cancel.setVisible(False)
        self._open_folder.setVisible(saved > 0)
        self._close.setVisible(True)
        self._fit()

    def _on_cancel(self) -> None:
        progress = self._progress
        if progress.finished or progress.cancelling:
            return
        downloaded = progress.bytes_downloaded()
        if downloaded > 0 or progress.saved_count() > 0:
            text = format_size(downloaded) if downloaded else "parte de las horas"
            if not self._confirm_cancel(text):
                return
        progress.request_cancel()
        self.refresh()
        self.cancel_requested.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 (nombre de Qt)
        if self._progress.finished:
            self._timer.stop()
            event.accept()
            self.dismissed.emit()
        else:  # mientras se exporta, la X solo oculta el panel: la exportación sigue
            event.ignore()
            self.hide()

    def reject(self) -> None:
        self.close()  # Esc: igual que la X
