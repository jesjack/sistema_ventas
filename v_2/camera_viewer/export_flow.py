from __future__ import annotations

import os
import queue
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from .clip import Clip
from .export_bar import EXPORTING, FINISHED, IDLE, PREVIEW, ExportBar
from .export_clip import (
    CANCELLED_TEXT,
    ClipExport,
    ClipRange,
    default_export_folder,
    estimate_bytes,
    format_size,
    make_folder,
    parse_folder,
    start_export,
)
from .export_progress import ExportProgress

# Flujo de exportación de un clip corto: marcar inicio/fin (o "últimos 30 s") ->
# VISTA PREVIA acotada al rango (la reproducción normal con los mismos controles,
# más "Inicio del clip") -> confirmar (canales, carpeta) -> descarga en segundo
# plano con avance -> resultado. Es lógica sin ventanas propias: MainWindow le
# da la barra, la línea de tiempo y el cliente, y sus diálogos (ask_after_seconds,
# choose_folder, open_folder) para poder probarla sin abrir nada.

MIN_CLIP_SECONDS = 1.0
LAST_SECONDS = 30.0
POLL_MS = 150
SETTINGS_FOLDER_KEY = "export_folder"


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {rest:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def range_text(clip_range: ClipRange) -> str:
    return f"{clip_range.start:%H:%M:%S} – {clip_range.end:%H:%M:%S} ({format_duration(clip_range.duration)})"


def _file_size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


class ExportFlow(QObject):
    def __init__(
        self,
        client,
        timeline,
        bar: ExportBar,
        clips_provider: Callable[[], dict[int, list[Clip]]],
        notify: Callable[[str], None],
        ask_after_seconds: Callable[[], float | None],
        choose_folder: Callable[[Path], Path | None],
        open_folder: Callable[[Path], None],
        settings=None,
        starter=start_export,
        now: Callable[[], datetime] = datetime.now,
        parent: QObject | None = None,
        preview_opener: Callable[[ClipRange], ClipRange | None] | None = None,
        progress_opener: Callable[[ExportProgress], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.client, self.timeline, self.bar = client, timeline, bar
        self._clips_provider, self._notify = clips_provider, notify
        self._ask_after_seconds, self._choose_folder, self._open_folder = ask_after_seconds, choose_folder, open_folder
        self._settings, self._starter, self._now = settings, starter, now
        # En la ventana principal la vista previa y el guardado viven en OTRA ventana (ver
        # clip_export_dialog.py): `preview_opener` la abre y devuelve el rango con que quedó.
        self._preview_opener = preview_opener
        # En la ventana de guardado el avance se muestra en una ventana propia (save_progress_dialog.py):
        # al empezar a guardar se le entrega el `ExportProgress` que este flujo va actualizando.
        self._progress_opener = progress_opener
        self.progress: ExportProgress | None = None

        self.marks: list[datetime | None] = [None, None]
        self.preview_range: ClipRange | None = None
        self.export: ClipExport | None = None
        self._states: dict[int, str] = {}
        self._results: dict[int, str] = {}
        self._failures: dict[int, str] = {}
        self._warnings: dict[int, str] = {}
        self._folder = self._load_folder()
        self._folder_ok = True  # False mientras el campo de carpeta tiene algo que no sirve
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

        bar.mark_start_clicked.connect(self.mark_start)
        bar.mark_end_clicked.connect(self.mark_end)
        bar.clear_marks_clicked.connect(self.clear_marks)
        bar.save_clicked.connect(self.save_clip)
        bar.save_last_clicked.connect(self.save_last)
        bar.restart_clicked.connect(self.restart_clip)
        bar.confirm_clicked.connect(self.confirm)
        bar.cancel_preview_clicked.connect(self.cancel_preview)
        bar.cancel_export_clicked.connect(self.cancel_export)
        bar.open_folder_clicked.connect(lambda: self._open_folder(self._folder))
        bar.choose_folder_clicked.connect(self.choose_folder)
        bar.dismiss_clicked.connect(self.dismiss_result)
        bar.channels_changed.connect(self._refresh_preview_info)
        bar.folder_edited.connect(self._folder_edited)
        bar.folder_committed.connect(self._folder_committed)

    # -- carpeta ------------------------------------------------------------------------

    def _load_folder(self) -> Path:
        if self._settings is not None:
            saved = self._settings.value(SETTINGS_FOLDER_KEY)
            if saved:
                return Path(str(saved))
        return default_export_folder()

    def choose_folder(self) -> None:
        chosen = self._choose_folder(self._folder)
        if chosen is not None:
            self._folder = Path(chosen)
            if self._settings is not None:
                self._settings.setValue(SETTINGS_FOLDER_KEY, str(self._folder))
            self._refresh_preview_info()

    def _folder_edited(self, text: str) -> None:
        """Campo de carpeta (ventana de guardado): con cada tecla, en rojo y sin poder guardar
        mientras lo escrito no sea una carpeta utilizable."""
        path = parse_folder(text)
        self._folder_ok = path is not None
        if path is not None:
            self._folder = path
        self.bar.set_folder_valid(self._folder_ok)
        self._update_confirm()

    def _folder_committed(self, text: str) -> None:
        path = parse_folder(text)
        if path is None:
            self._notify(f"«{text.strip()}» no es una carpeta válida; se conserva {self._folder}.")
            self._folder_ok = True
        else:
            self._folder = path
            if self._settings is not None:
                self._settings.setValue(SETTINGS_FOLDER_KEY, str(path))
        self._refresh_preview_info()

    def _update_confirm(self) -> None:
        self.bar.enable_confirm(self._folder_ok and bool(self.bar.selected_channels()))

    # -- marcas -----------------------------------------------------------------------------

    def _clock(self) -> datetime | None:
        return self.client.control.media_now()

    def mark_start(self) -> None:
        moment = self._clock()
        if moment is None:
            return
        if self.preview_range is not None:
            if self.preview_range.end - moment < timedelta(seconds=MIN_CLIP_SECONDS):
                self._notify("El inicio debe quedar antes del fin del clip.")
                return
            self._set_preview_range(ClipRange(moment, self.preview_range.end))
            return
        self.marks[0] = moment
        if self.marks[1] is not None and self.marks[1] - moment < timedelta(seconds=MIN_CLIP_SECONDS):
            self.marks[1] = None
        self._refresh_marks()

    def mark_end(self) -> None:
        moment = self._clock()
        if moment is None:
            return
        if self.preview_range is not None:
            if moment - self.preview_range.start < timedelta(seconds=MIN_CLIP_SECONDS):
                self._notify("El fin debe quedar después del inicio del clip.")
                return
            self._set_preview_range(ClipRange(self.preview_range.start, moment))
            return
        self.marks[1] = moment
        if self.marks[0] is not None and moment - self.marks[0] < timedelta(seconds=MIN_CLIP_SECONDS):
            self.marks[0] = None
        self._refresh_marks()

    def clear_marks(self) -> None:
        self.marks = [None, None]
        self._refresh_marks()

    def _marked_range(self) -> ClipRange | None:
        start, end = self.marks
        if start is not None and end is not None and end - start >= timedelta(seconds=MIN_CLIP_SECONDS):
            return ClipRange(start, end)
        return None

    def _refresh_marks(self) -> None:
        clip_range = self._marked_range()
        if clip_range is not None:
            self.timeline.set_marks(clip_range.start, clip_range.end)
            self.bar.set_marks(True, range_text(clip_range))
            return
        start, end = self.marks
        # Con una sola marca la línea de tiempo la dibuja suelta, con su hora, a la espera de la otra.
        self.timeline.set_marks(start, None) if start is not None else self.timeline.set_marks(None, end)
        if start is not None:
            self.bar.set_marks(False, f"Inicio {start:%H:%M:%S} — falta marcar el fin")
        elif end is not None:
            self.bar.set_marks(False, f"Fin {end:%H:%M:%S} — falta marcar el inicio")
        else:
            self.bar.set_marks(False, "Marca el inicio y el fin del clip")

    # -- guardar -----------------------------------------------------------------------------

    def save_clip(self) -> None:
        clip_range = self._marked_range()
        if clip_range is None:
            self._notify("Marca primero el inicio y el fin del clip.")
            return
        self.enter_preview(clip_range)

    def save_last(self) -> None:
        """Últimos 30 s hasta el punto actual; pregunta si incluir también los 30 s siguientes."""
        moment = self._clock()
        if moment is None:
            return
        after = self._ask_after_seconds()
        if after is None:
            return
        clips = [clip for clips in self._clips_provider().values() for clip in clips]
        earliest = min((clip.start for clip in clips), default=None)
        latest = max((clip.end for clip in clips), default=None)
        latest = min(latest, self._now()) if latest is not None else self._now()
        clip_range = ClipRange.around(moment, LAST_SECONDS, after, earliest, latest)
        if clip_range.duration < MIN_CLIP_SECONDS:
            self._notify("No hay grabación suficiente en ese tramo.")
            return
        if after and clip_range.end < moment + timedelta(seconds=after):
            self._notify(f"Solo hay {format_duration((clip_range.end - moment).total_seconds())} de grabación posterior.")
        self.enter_preview(clip_range)

    # -- vista previa ------------------------------------------------------------------------

    def enter_preview(self, clip_range: ClipRange) -> None:
        if not self._available_channels(clip_range):
            self._notify("No hay grabación en ese tramo.")
            return
        self.marks = [clip_range.start, clip_range.end]
        if self._preview_opener is not None:
            final = self._preview_opener(clip_range)
            if final is not None:
                self.marks = [final.start, final.end]
            self._refresh_marks()
            return
        self.preview_range = clip_range
        control = self.client.control
        control.set_bounds(clip_range.start, clip_range.end)
        self.client.set_reverse(False)
        if self.client.playback_active:
            self.client.seek(clip_range.start, resume=True)
        else:  # ventana de guardado: su propia reproducción, que arranca aquí
            self.client.play_from(clip_range.start, self._clips_provider())
        self.timeline.set_export_range(clip_range.start, clip_range.end)
        if self.export is None or self.export.finished():
            self.bar.set_state(PREVIEW)
        self._refresh_preview_info()
        self._notify("Vista previa del clip: revísalo y confirma para guardarlo.")

    def adjust_range(self, start: datetime, end: datetime) -> None:
        """Cambia el rango de la vista previa (asas de la línea de tiempo). Mínimo 1 s."""
        if self.preview_range is None:
            return
        if end - start < timedelta(seconds=MIN_CLIP_SECONDS):
            self._notify("El clip debe durar al menos 1 segundo.")
            self.timeline.set_export_range(self.preview_range.start, self.preview_range.end)
            return
        self._set_preview_range(ClipRange(start, end))

    def final_range(self) -> ClipRange | None:
        """El rango con que quedó el clip (para que la ventana principal actualice sus marcas)."""
        if self.preview_range is not None:
            return self.preview_range
        return self._marked_range()

    def _set_preview_range(self, clip_range: ClipRange) -> None:
        self.marks = [clip_range.start, clip_range.end]
        self.preview_range = clip_range
        self.client.control.set_bounds(clip_range.start, clip_range.end)
        self.timeline.set_export_range(clip_range.start, clip_range.end)
        self._refresh_preview_info()

    def _available_channels(self, clip_range: ClipRange) -> set[int]:
        return {
            channel
            for channel, clips in self._clips_provider().items()
            if any(clip.start < clip_range.end and clip.end > clip_range.start for clip in clips)
        }

    def _refresh_preview_info(self) -> None:
        clip_range = self.preview_range
        if clip_range is None:
            return
        self.bar.set_marks(True, range_text(clip_range))
        self.bar.set_available_channels(self._available_channels(clip_range))
        channels = self.bar.selected_channels()
        size = format_size(estimate_bytes(clip_range, max(1, len(channels))))
        self.bar.set_preview_info(self._folder, f"≈ {size} ({len(channels)} canal{'es' if len(channels) != 1 else ''})")
        self._update_confirm()

    def restart_clip(self) -> None:
        if self.preview_range is None:
            return
        self.client.set_reverse(False)
        self.client.seek(self.preview_range.start, resume=True)

    def at_bound_action(self) -> bool:
        """Reanudar (o pausa) estando detenido en un extremo del rango: vuelve a empezar desde el
        otro extremo en vez de no hacer nada. True = ya se atendió."""
        if self.preview_range is None:
            return False
        reached = self.client.control.bound_reached()
        if reached == "end":
            self.client.seek(self.preview_range.start, resume=True)
            return True
        if reached == "start":
            self.client.seek(self.preview_range.end, resume=True)
            return True
        return False

    def leave_preview(self) -> None:
        """Sale de la vista previa (la reproducción vuelve a ser libre). Las marcas se conservan."""
        self.client.control.clear_bounds()
        self.preview_range = None
        if self.export is None or self.export.finished():
            if self.bar.state == PREVIEW:
                self.bar.set_state(IDLE)
        self._refresh_marks()

    def cancel_preview(self) -> None:
        self.leave_preview()
        self._notify("Vista previa cancelada.")

    # -- exportar ------------------------------------------------------------------------------

    def confirm(self) -> None:
        clip_range = self.preview_range
        if clip_range is None:
            return
        channels = self.bar.selected_channels()
        if not channels:
            self._notify("Elige al menos un canal.")
            return
        try:
            make_folder(self._folder)
            probe = self._folder / ".camera_viewer_write_test"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            self._notify(f"No se puede guardar en {self._folder}: {exc}")
            return
        self._states = {channel: "En cola…" for channel in channels}
        self._results, self._failures, self._warnings = {}, {}, {}
        self.export = self._starter(
            self.client.host, self.client.username, self.client.password, channels, clip_range, self._folder
        )
        self.client.control.clear_bounds()
        self.preview_range = None
        self.marks = [clip_range.start, clip_range.end]
        self.bar.set_state(EXPORTING)
        self.bar.set_marks(True, range_text(clip_range))
        self._show_progress()
        self._timer.start()
        self.progress = ExportProgress(clip_range, self._folder, channels, parent=self)
        if self._progress_opener is not None:
            self._progress_opener(self.progress)

    def _show_progress(self) -> None:
        self.bar.set_message("   ".join(f"CAM {ch}: {text}" for ch, text in self._states.items()))

    def _poll(self) -> None:
        handle = self.export
        if handle is None:
            self._timer.stop()
            return
        finished = None
        while True:
            try:
                event = handle.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            progress = self.progress
            if kind == "state":
                self._states[event[1]] = event[2]
                if progress is not None:
                    progress.set_phase(event[1], event[3] if len(event) > 3 else None, event[2])
            elif kind == "progress":
                if progress is not None:
                    progress.set_bytes(event[1], event[2])
            elif kind == "done":
                self._results[event[1]] = event[2]
                self._states[event[1]] = "Listo" if event[3] is None else f"Listo ({event[3]})"
                if event[3]:
                    self._warnings[event[1]] = event[3]
                if progress is not None:
                    progress.mark_done(event[1], event[2], _file_size(event[2]), event[3])
            elif kind == "failed":
                self._failures[event[1]] = event[2]
                self._states[event[1]] = f"Falló: {event[2]}"
                if progress is not None:
                    progress.mark_failed(event[1], event[2], event[2] == CANCELLED_TEXT)
            elif kind == "finished":
                finished = event[1]
        if finished is None:
            self._show_progress()
            self._announce_progress()
            return
        self._timer.stop()
        total = len(self._states)
        saved = len(self._results)
        if saved == total:
            summary = f"Guardado en {self._folder}: {saved} archivo{'s' if saved != 1 else ''}."
        elif saved:
            summary = f"Se guardaron {saved} de {total}. " + " ".join(f"CAM {c}: {m}." for c, m in self._failures.items())
        else:
            summary = "No se pudo guardar. " + " ".join(f"CAM {c}: {m}." for c, m in self._failures.items())
        if self._warnings:
            summary += " Aviso: " + "; ".join(f"CAM {c} {w}" for c, w in self._warnings.items()) + "."
        self.bar.set_state(FINISHED)
        self.bar.set_message(summary)
        self._notify(summary)
        if self.progress is not None:
            self.progress.finish()
            self._announce_progress()

    def _announce_progress(self) -> None:
        if self.progress is not None:
            self.progress.changed.emit()

    def cancel_export(self) -> None:
        if self.export is not None:
            self.export.cancel()
            self.bar.set_message("Cancelando…")
            if self.progress is not None:
                self.progress.request_cancel()

    def dismiss_result(self) -> None:
        self.export = None
        self.progress = None
        self.bar.set_state(IDLE)
        self._refresh_marks()

    def return_to_preview(self) -> None:
        """Tras guardar (o cancelar) desde la ventana de guardado: vuelve a la vista previa del mismo
        clip para ajustarlo o reintentar."""
        self.export = None
        self.progress = None
        start, end = self.marks
        if start is not None and end is not None:
            self.enter_preview(ClipRange(start, end))

    def folder(self) -> Path:
        return self._folder

    # -- estado de la reproducción ---------------------------------------------------------------

    def set_playback_active(self, active: bool) -> None:
        self.bar.set_active(active)
        if not active:
            self.leave_preview()
        elif self.bar.state == IDLE:
            self._refresh_marks()

    def export_running(self) -> bool:
        return self.export is not None and not self.export.finished()
