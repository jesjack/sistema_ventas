from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .export_clip import (
    PHASE_CONVERTING,
    PHASE_DOWNLOADING,
    PHASE_QUEUED,
    PHASE_RETRYING,
    PHASE_VERIFYING,
    format_size,
)
from .export_flow import format_duration
from .export_progress import PHASE_CANCELLED, PHASE_DONE, PHASE_FAILED, ExportProgress

# Ventana de avance del guardado de un clip: lo que se abre al pulsar "Guardar" en la ventana
# del clip. Muestra el avance total y una tarjeta por canal (fase, barra, MB, velocidad,
# tiempo restante y, al terminar, el archivo o el motivo del fallo) y tiene el botón de
# cancelar. Solo dibuja lo que dice el ExportProgress (export_progress.py) y avisa con
# señales; quien decide qué hacer es ClipExportDialog. Su resultado (`finished(int)`):
#   Accepted -> "Cerrar" (cierra también la ventana del clip); BACK -> "Volver al clip".

BACK = 2
REFRESH_MS = 250  # repinta también sin avisos: la velocidad y el tiempo transcurrido siguen corriendo

COLOR_ACTIVE = "#3B82F6"
COLOR_OK = "#22C55E"
COLOR_ERROR = "#EF4444"
COLOR_WARN = "#F59E0B"
COLOR_IDLE = "#94A3B8"

CARD_STYLE = (
    "QFrame#card { background-color: rgba(127, 127, 127, 28); border: 1px solid rgba(127, 127, 127, 90); border-radius: 6px; }"
    " QFrame#card QLabel { background: transparent; }"  # (la hoja de estilo de la app pinta de oscuro todos los QWidget)
)
MUTED = "color: #94A3B8;"


def bar_style(color: str) -> str:
    return (
        "QProgressBar { border: 1px solid rgba(127, 127, 127, 110); border-radius: 4px; background-color: rgba(127, 127, 127, 40);"
        " text-align: center; min-height: 16px; }"
        f" QProgressBar::chunk {{ background-color: {color}; border-radius: 3px; }}"
    )


def format_clock(seconds: float) -> str:
    seconds = int(round(max(0.0, seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def ask_cancel(parent: QWidget, downloaded: str) -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, "Cancelar el guardado", "", QMessageBox.StandardButton.NoButton, parent)
    box.setText(f"¿Cancelar el guardado?\n\nYa se descargaron {downloaded}; lo que no haya terminado de guardarse se perderá.")
    stop = box.addButton("Sí, cancelar", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Seguir guardando", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.exec()
    return box.clickedButton() is stop


class ChannelCard(QFrame):
    """Una tarjeta por canal: nombre, fase, barra y el detalle (MB, velocidad, resultado)."""

    def __init__(self, channel: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.setObjectName("card")
        self.setStyleSheet(CARD_STYLE)
        self._icon = QLabel("●")
        self._icon.setFixedWidth(18)
        title = QLabel(f"CAM {channel}")
        title.setStyleSheet("font-weight: bold;")
        self._phase = QLabel()
        self._phase.setStyleSheet("font-weight: bold;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(True)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(MUTED)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._icon)
        head.addWidget(title)
        head.addSpacing(8)
        head.addWidget(self._phase, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self._bar)
        layout.addWidget(self._detail)

    def refresh(self, progress: ExportProgress) -> None:
        item = progress.channel(self.channel)
        phase = item.phase
        color, glyph = COLOR_IDLE, "●"
        percent = int(progress.download_fraction(self.channel) * 100)
        if phase == PHASE_QUEUED:
            headline = "En cola"
            detail = "Esperando turno con el DVR (solo se descargan dos canales a la vez)."
            self._set_bar(0, "En cola")
        elif phase in (PHASE_DOWNLOADING, PHASE_RETRYING):
            color = COLOR_ACTIVE
            headline = "Descargando del DVR" if phase == PHASE_DOWNLOADING else "Reintentando la descarga"
            self._set_bar(int(progress.download_fraction(self.channel) * 1000), f"{percent} %")
            detail = self._download_detail(progress, item)
        elif phase == PHASE_CONVERTING:
            color, headline = COLOR_ACTIVE, "Convirtiendo a MP4"
            self._set_bar(1000, "Convirtiendo…")  # la descarga ya está completa
            detail = "La descarga terminó; se está guardando el archivo sin recodificar."
        elif phase == PHASE_VERIFYING:
            color, headline = COLOR_ACTIVE, "Comprobando el archivo"
            self._set_bar(1000, "Verificando…")
            detail = "Se verifica que el video se abra y dure lo esperado."
        elif phase == PHASE_DONE:
            color, glyph, headline = COLOR_OK, "✔", "Guardado"
            self._set_bar(1000, "100 %")
            name = item.result_path.rsplit("/", 1)[-1] if item.result_path else ""
            size = f" · {format_size(item.result_size)}" if item.result_size else ""
            detail = f"{name}{size}"
            if item.warning:
                detail += f"\n⚠ Aviso: {item.warning}"
        elif phase == PHASE_CANCELLED:
            color, glyph, headline = COLOR_WARN, "■", "Cancelado"
            self._bar.setFormat("Cancelado")
            detail = "Este canal no se guardó."
        else:  # PHASE_FAILED
            color, glyph, headline = COLOR_ERROR, "✘", "No se pudo guardar"
            self._bar.setFormat("Falló")
            detail = item.error or ""
        self._icon.setText(glyph)
        self._icon.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._phase.setText(headline)
        self._phase.setStyleSheet(f"font-weight: bold; color: {color};")
        self._bar.setStyleSheet(bar_style(color))
        self._detail.setText(detail)
        # Un QLabel con ajuste de línea dentro de un layout no pide el alto de sus líneas extra: se le dice.
        self._detail.setMinimumHeight(self._detail.fontMetrics().lineSpacing() * (detail.count("\n") + 1))
        self._detail.setStyleSheet("color: #FBBF24;" if item.warning and phase == PHASE_DONE else MUTED)

    def _set_bar(self, value: int, text: str) -> None:
        self._bar.setValue(value)
        self._bar.setFormat(text)

    def _download_detail(self, progress: ExportProgress, item) -> str:
        expected = progress.expected_bytes
        done = format_size(item.bytes_done)
        if item.phase == PHASE_RETRYING:
            return "La descarga se cortó; se vuelve a pedir el tramo al DVR."
        if item.bytes_done >= expected * 0.99:
            return f"{done} recibidos · terminando…"
        parts = [f"{done} de ≈ {format_size(expected)}"]
        speed = progress.speed(item.channel)
        if speed is not None:
            parts.append("atascada: el DVR no envía datos" if speed <= 0 else f"{format_size(speed)}/s")
            eta = progress.eta(item.channel)
            if eta is not None:
                parts.append(f"quedan ≈ {format_clock(eta)}")
        return " · ".join(parts)


class SaveProgressDialog(QDialog):
    cancel_requested = Signal()
    open_folder_requested = Signal()

    def __init__(
        self,
        progress: ExportProgress,
        parent: QWidget | None = None,
        confirm_cancel: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Guardando el clip")
        self.setModal(True)
        self.setMinimumWidth(620)
        self._progress = progress
        self._confirm_cancel = confirm_cancel or (lambda downloaded: ask_cancel(self, downloaded))
        self._settled = False  # ya se mostró el resultado final

        clip_range = progress.clip_range
        self._headline = QLabel()
        self._headline.setStyleSheet("font-size: 15pt; font-weight: bold;")
        channels_text = f"{len(progress.channels)} canal{'es' if len(progress.channels) != 1 else ''}"
        subtitle = QLabel(
            f"{clip_range.start:%d/%m/%Y}  {clip_range.start:%H:%M:%S} – {clip_range.end:%H:%M:%S}"
            f"  ({format_duration(clip_range.duration)} de video) · {channels_text}"
        )
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

        self.cards: dict[int, ChannelCard] = {}
        cards_layout = QVBoxLayout()
        cards_layout.setSpacing(8)
        for channel in progress.channels:
            card = ChannelCard(channel)
            self.cards[channel] = card
            cards_layout.addWidget(card)

        self._cancel = QPushButton("Cancelar")
        self._open_folder = QPushButton("Abrir carpeta")
        self._back = QPushButton("Volver al clip")
        self._close = QPushButton("Cerrar")
        for button in (self._cancel, self._open_folder, self._back, self._close):
            button.setAutoDefault(False)
            button.setMinimumHeight(32)
            button.setMinimumWidth(110)
        self._cancel.clicked.connect(self._on_cancel)
        self._open_folder.clicked.connect(self.open_folder_requested)
        self._back.clicked.connect(lambda: self.done(BACK))
        self._close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for button in (self._cancel, self._open_folder, self._back, self._close):
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

    # -- estado ---------------------------------------------------------------------------------

    def refresh(self) -> None:
        progress = self._progress
        for card in self.cards.values():
            card.refresh(progress)
        fraction = progress.overall_fraction()
        percent = int(fraction * 100) if not progress.finished else 100
        self._overall.setValue(1000 if progress.finished else int(fraction * 1000))
        self._overall.setFormat(f"{percent} %")
        if progress.finished:
            self._show_result()
            return
        text = f"Transcurrido {format_clock(progress.elapsed())}"
        eta = progress.overall_eta()
        if eta is not None:
            text += f" · quedan ≈ {format_clock(eta)}"
        if progress.cancelling:
            self._headline.setText("Cancelando…")
        else:
            self._headline.setText("Guardando el clip")
        self._overall_text.setText(text)
        self._cancel.setVisible(True)
        self._cancel.setEnabled(not progress.cancelling)
        self._cancel.setText("Cancelando…" if progress.cancelling else "Cancelar")
        for button in (self._open_folder, self._back, self._close):
            button.setVisible(False)

    def _show_result(self) -> None:
        if self._settled:
            return
        self._settled = True
        self._timer.stop()
        progress = self._progress
        saved, total = progress.saved_count(), progress.total_count()
        if saved == total:
            headline, color = "Listo: el clip se guardó", COLOR_OK
        elif saved == 0 and progress.was_cancelled():
            # Se canceló sin haber guardado nada: no hay resultado que mostrar, se vuelve al clip.
            self._headline.setText("Cancelado")
            QTimer.singleShot(0, lambda: self.done(BACK))
            return
        elif saved == 0:
            headline, color = "No se pudo guardar el clip", COLOR_ERROR
        elif progress.was_cancelled():
            headline, color = f"Cancelado: se guardaron {saved} de {total} canales", COLOR_WARN
        else:
            headline, color = f"Se guardaron {saved} de {total} canales", COLOR_WARN
        self._headline.setText(headline)
        self._headline.setStyleSheet(f"font-size: 15pt; font-weight: bold; color: {color};")
        self._overall.setStyleSheet(bar_style(color) + " QProgressBar { min-height: 22px; font-weight: bold; }")
        if saved < total:  # "100 %" engañaría: se dice cuántos canales quedaron
            self._overall.setValue(int(1000 * saved / total))
            self._overall.setFormat(f"{saved} de {total} canales guardados")
        self._overall_text.setText(f"Tardó {format_clock(progress.elapsed())}")
        self._cancel.setVisible(False)
        self._open_folder.setVisible(saved > 0)
        self._back.setVisible(saved < total)
        self._close.setVisible(True)
        self._close.setDefault(True)
        self.resize(self.width(), max(self.height(), self.sizeHint().height()))  # los avisos de varias líneas piden más alto

    # -- acciones ---------------------------------------------------------------------------------

    def _on_cancel(self) -> None:
        progress = self._progress
        if progress.finished or progress.cancelling:
            return
        if progress.bytes_downloaded() > 0 or progress.saved_count() > 0:
            downloaded = format_size(progress.bytes_downloaded()) if progress.bytes_downloaded() else "parte del clip"
            if not self._confirm_cancel(downloaded):
                return
        progress.request_cancel()
        self.refresh()
        self.cancel_requested.emit()

    def reject(self) -> None:
        """Esc o la X: mientras se guarda equivale a "Cancelar" (con confirmación); al terminar, a "Cerrar"."""
        if self._progress.finished:
            self.accept()
        else:
            self._on_cancel()

    def done(self, result: int) -> None:
        self._timer.stop()
        try:
            self._progress.changed.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass
        super().done(result)
