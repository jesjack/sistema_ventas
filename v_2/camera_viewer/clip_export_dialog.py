from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QVBoxLayout, QWidget

from .camera_grid import CameraGrid
from .clip import Clip
from .clip_timeline import ClipTimeline
from .export_bar import ExportBar
from .export_clip import ClipRange, start_export
from .export_flow import ExportFlow
from .playback_controls import JUMP_SECONDS, PlaybackControls

# Ventana de guardado de un clip: los 4 canales, una línea de tiempo propia con el
# segmento (y un margen para poder alargarlo), controles de reproducción propios
# (pausa, ±10 s, sentido, velocidad, "Inicio del clip") y las opciones de guardado
# (canales, carpeta, tamaño estimado, Guardar/Cancelar y el avance). Usa su propio
# cliente de reproducción, así la ventana principal queda en pausa y no se mezcla.
# La lógica es la de ExportFlow (export_flow.py), la misma de siempre.

CONTEXT_MIN = 10.0  # s de margen a cada lado del clip...
CONTEXT_MAX = 120.0  # ...entre 10 s y 2 min, o el 25 % de su duración
TICK_MS = 100
STARTING_STATUS = "Cargando el clip…"


class ClipExportDialog(QDialog):
    def __init__(
        self,
        client,
        clips_by_channel: dict[int, list[Clip]],
        clip_range: ClipRange,
        settings: QSettings | None = None,
        now=datetime.now,
        parent: QWidget | None = None,
        starter=start_export,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Guardar clip")
        self.resize(1180, 840)
        self._client = client
        self._clips = clips_by_channel
        self._initial_range = clip_range
        self._final_range: ClipRange | None = clip_range
        self._connected = False
        self._started = False

        channels = tuple(sorted(clips_by_channel)) or (1, 2, 3, 4)
        self.grid = CameraGrid(channels, initial_status=STARTING_STATUS)
        self.controls = PlaybackControls()
        self.timeline = ClipTimeline()
        self.bar = ExportBar(channels)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #9CA3AF;")
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.grid, stretch=1)
        layout.addWidget(self.controls)
        layout.addWidget(self.timeline)
        layout.addWidget(self.bar)
        layout.addWidget(self._status)

        self._set_context(clip_range, now)
        self.timeline.set_coverage(clips_by_channel)
        self.timeline.set_export_range(clip_range.start, clip_range.end)
        self.timeline.draw_playhead(clip_range.start)

        self.flow = ExportFlow(
            client,
            self.timeline,
            self.bar,
            clips_provider=lambda: self._clips,
            notify=self._status.setText,
            ask_after_seconds=lambda: None,
            choose_folder=self._choose_folder,
            open_folder=self._open_folder,
            settings=settings,
            starter=starter,
            now=now,
            parent=self,
        )
        self.bar.cancel_preview_clicked.connect(self.reject)  # "Cancelar" cierra la ventana
        self.bar.dismiss_clicked.connect(self.accept)  # "Cerrar" tras guardar
        self.controls.pause_clicked.connect(self._toggle_pause)
        self.controls.jump_clicked.connect(self._jump)
        self.controls.reverse_toggled.connect(self._set_reverse)
        self.controls.speed_selected.connect(self._set_speed)
        self.timeline.seek_requested.connect(self._seek)
        self.timeline.range_changed.connect(self._range_dragged)

        for key, action in (
            (Qt.Key.Key_Space, self._toggle_pause),
            (Qt.Key.Key_Left, lambda: self._jump(-JUMP_SECONDS)),
            (Qt.Key.Key_Right, lambda: self._jump(JUMP_SECONDS)),
        ):
            QShortcut(QKeySequence(key), self).activated.connect(action)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        QTimer.singleShot(0, self._start)

    # -- contexto del clip ------------------------------------------------------------------

    def _set_context(self, clip_range: ClipRange, now) -> None:
        pad = timedelta(seconds=min(CONTEXT_MAX, max(CONTEXT_MIN, clip_range.duration * 0.25)))
        spans = [clip for clips in self._clips.values() for clip in clips]
        earliest = min((clip.start for clip in spans), default=clip_range.start)
        latest = min(max((clip.end for clip in spans), default=clip_range.end), now())
        start = max(clip_range.start - pad, min(earliest, clip_range.start))
        end = min(clip_range.end + pad, max(latest, clip_range.end))
        self.timeline.set_context(start, end)

    # -- arranque y cierre ---------------------------------------------------------------------

    def _start(self) -> None:
        if self._started:
            return
        self._started = True
        client = self._client
        client.recording_frame_ready.connect(self._on_frame)
        client.recording_channel_status.connect(self._on_status)
        self._connected = True
        client.set_speed(1.0)
        client.set_reverse(False)
        self.controls.set_active(True)
        self.controls.set_speed(1.0)
        self.controls.set_reverse(False)
        self.bar.set_active(True)
        self.flow.enter_preview(self._initial_range)
        self._timer.start()

    def final_range(self) -> ClipRange | None:
        return self._final_range

    def done(self, result: int) -> None:
        self._timer.stop()
        flow_range = self.flow.final_range()
        if flow_range is not None:
            self._final_range = flow_range
        if self.flow.export_running():
            self.flow.cancel_export()
        if self._connected:
            self._connected = False
            self._client.recording_frame_ready.disconnect(self._on_frame)
            self._client.recording_channel_status.disconnect(self._on_status)
        self._client.control.clear_bounds()
        self._client.stop_playback()
        super().done(result)

    # -- señales del cliente de reproducción -----------------------------------------------------

    def _on_frame(self, channel: int, frame) -> None:
        panel = self.grid.panels.get(channel)
        if panel is not None:
            panel.set_frame(frame)
        self._client.notify_recording_frame_consumed(channel)

    def _on_status(self, channel: int, text: str) -> None:
        panel = self.grid.panels.get(channel)
        if panel is not None:
            panel.set_status(text)

    # -- controles propios -------------------------------------------------------------------------

    def _tick(self) -> None:
        moment = self._client.control.media_now()
        if moment is not None:
            self.timeline.draw_playhead(moment)
        paused = self._client.control.paused
        if paused != self.controls.is_paused():
            self.controls.set_paused(paused)  # p. ej. se pausó sola al llegar al final del clip

    def _toggle_pause(self) -> None:
        if self.flow.at_bound_action():
            self.controls.set_paused(False)  # detenido en un extremo: reanudar = volver a empezar
            return
        self.controls.set_paused(self._client.toggle_pause())

    def _jump(self, seconds: int) -> None:
        current = self._client.control.media_now()
        if current is not None:
            self._client.seek(current + timedelta(seconds=seconds))  # el reloj lo deja dentro del clip

    def _seek(self, moment: datetime) -> None:
        self._client.seek(moment)

    def _set_reverse(self, reverse: bool) -> None:
        self._client.set_reverse(reverse)
        self.controls.set_reverse(reverse)

    def _set_speed(self, speed: float) -> None:
        self._client.set_speed(speed)
        self.controls.set_speed(speed)

    def _range_dragged(self, start: datetime, end: datetime) -> None:
        context = self.timeline.context()
        if context is not None:
            start, end = max(start, context[0]), min(end, context[1])
        self.flow.adjust_range(start, end)

    # -- carpeta ----------------------------------------------------------------------------------------

    def _choose_folder(self, current: Path) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar los clips", str(current))
        return Path(chosen) if chosen else None

    def _open_folder(self, folder: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
