from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from .camera_grid import CameraGrid
from .clip import Clip
from .clip_timeline import ClipTimeline
from .export_bar import ExportBar
from .export_clip import ClipRange, start_export
from .export_flow import ExportFlow
from .export_progress import ExportProgress
from .playback_controls import JUMP_SECONDS, PlaybackControls
from .save_progress_dialog import BACK, SaveProgressDialog

# Ventana de guardado de un clip: arriba las opciones de guardado (carpeta con su
# "Examinar…", tamaño estimado, Guardar/Cancelar y luego el avance), los 4 canales con su
# casilla (desmarcar un canal lo deja negro: no se guardará), controles de reproducción
# propios (pausa, ±10 s, sentido, velocidad, "Inicio del clip") y una línea de tiempo propia
# con el segmento (y un margen) cuyas asas, con su hora y la duración, ajustan el inicio y el
# fin. Usa su propio cliente de reproducción, así la ventana principal queda en pausa.
# Al pulsar "Guardar" su reproducción se detiene (libera al DVR) y se abre encima la ventana de
# avance (save_progress_dialog.py); "Cerrar" allí cierra también esta, y cancelar (o "Volver al
# clip") regresa a la vista previa del mismo clip.
# La lógica es la de ExportFlow (export_flow.py), la misma de siempre.

CONTEXT_MIN = 10.0  # s de margen a cada lado del clip...
CONTEXT_MAX = 120.0  # ...entre 10 s y 2 min, o el 25 % de su duración
TICK_MS = 100
STARTING_STATUS = "Cargando el clip…"
NOT_SAVED_MESSAGE = "Este canal no se descargará"
NO_RECORDING_MESSAGE = "Sin grabación en este rango"


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
        confirm_cancel=None,
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
        self._confirm_cancel = confirm_cancel  # None: la ventana de avance pregunta con un cuadro de diálogo
        self.progress_window: SaveProgressDialog | None = None

        channels = tuple(sorted(clips_by_channel)) or (1, 2, 3, 4)
        self.grid = CameraGrid(channels, initial_status=STARTING_STATUS)
        self.controls = PlaybackControls(with_restart=True)
        self.timeline = ClipTimeline()
        self.timeline.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # tras escribir una carpeta, un clic aquí devuelve la barra espaciadora a la pausa
        self.bar = ExportBar(channels, window_mode=True)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #9CA3AF;")
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.bar)
        layout.addWidget(self.grid, stretch=1)
        layout.addWidget(self.controls)
        layout.addWidget(self.timeline)
        layout.addWidget(self._status)

        for channel, panel in self.grid.panels.items():
            panel.set_corner_widget(self.bar.channel_check(channel))  # la casilla de cada canal vive en su panel
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)  # Enter (p. ej. en el campo de carpeta) no debe pulsar nada

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
            progress_opener=self._open_progress,
        )
        self.bar.cancel_preview_clicked.connect(self.reject)  # "Cancelar" cierra la ventana
        self.bar.dismiss_clicked.connect(self.accept)  # "Cerrar" tras guardar
        self.bar.channels_changed.connect(self._sync_channels)
        self.controls.pause_clicked.connect(self._toggle_pause)
        self.controls.restart_clicked.connect(self.flow.restart_clip)
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
        self._sync_channels()
        self._timer.start()

    def final_range(self) -> ClipRange | None:
        return self._final_range

    # -- ventana de avance del guardado -----------------------------------------------------------

    def _open_progress(self, progress: ExportProgress) -> None:
        self._client.stop_playback()  # las descargas del clip no compiten con las de la reproducción
        window = SaveProgressDialog(progress, self, self._confirm_cancel)
        window.cancel_requested.connect(self.flow.cancel_export)
        window.open_folder_requested.connect(lambda: self._open_folder(self.flow.folder()))
        window.finished.connect(self._progress_closed)
        self.progress_window = window
        window.open()

    def _progress_closed(self, result: int) -> None:
        self.progress_window = None
        if result == BACK:
            self.controls.set_paused(False)
            self.flow.return_to_preview()
            self._sync_channels()
        else:
            self.accept()  # "Cerrar": se terminó con este clip

    def done(self, result: int) -> None:
        self._timer.stop()
        window, self.progress_window = self.progress_window, None
        if window is not None:  # se cierra la ventana del clip (p. ej. la app): no repetir el aviso
            window.finished.disconnect(self._progress_closed)
        flow_range = self.flow.final_range()
        if flow_range is not None:
            self._final_range = flow_range
        if self.flow.export_running():
            self.flow.cancel_export()
        if window is not None:
            window.done(0)  # sin preguntar: la ventana del clip se está cerrando
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
        self._sync_channels()  # al mover el rango cambia qué canales tienen grabación

    def _sync_channels(self) -> None:
        """Un canal desmarcado (o sin grabación en el rango) se apaga: panel negro y un aviso."""
        for channel, panel in self.grid.panels.items():
            if not self.bar.channel_available(channel):
                panel.set_excluded(True, NO_RECORDING_MESSAGE)
            elif not self.bar.channel_check(channel).isChecked():
                panel.set_excluded(True, NOT_SAVED_MESSAGE)
            else:
                panel.set_excluded(False)

    # -- carpeta ----------------------------------------------------------------------------------------

    def _choose_folder(self, current: Path) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar los clips", str(current))
        return Path(chosen) if chosen else None

    def _open_folder(self, folder: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
