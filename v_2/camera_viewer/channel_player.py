from __future__ import annotations

import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import cv2

from .chunk_store import ChunkEntry, ChunkStore
from .clip import Clip
from .download_manager import DownloadPriority
from .light_query_manager import LightPriority
from .playback_control import PlaybackControl

# Reproductor de UN canal de grabaciones. Corre en su propio hilo y sirve el
# video desde el almacén local de bloques (chunk_store.py): solo descarga del
# DVR (por el embudo) lo que el almacén no tiene, y mientras reproduce trae
# por adelantado los bloques vecinos -- así el siguiente, el anterior y los
# saltos de ±10 s ya están en disco cuando se piden. Un salto NO reinicia el
# hilo: llega como una orden por PlaybackControl.
#
# Reglas de bloques:
#   - el primer bloque tras un salto a un punto NO descargado es corto (15 s),
#     para ver imagen pronto;
#   - los siguientes terminan en el primer minuto exacto que quede a más de
#     20 s (duran de 20 a 80 s, y 60 s una vez alineados);
#   - tras empezar un bloque se piden el siguiente (PREFETCH) y, si falta, lo
#     de atrás hasta el minuto anterior (BACKGROUND).

FIRST_CHUNK_SECONDS = 15.0
CHUNK_MIN_SECONDS = 20.0
KEEP_BEHIND = timedelta(seconds=120)
KEEP_AHEAD = timedelta(seconds=200)
MAX_CLIP_RETRIES = 3
CLIP_RETRY_BACKOFF = 1.5
BACKPRESSURE_POLL = 0.2
WAIT_POLL = 0.2
# Con velocidades altas se decodifican todos los cuadros pero solo se pintan
# ~30 por segundo: a x2 pintar los 60 saturaba el hilo de la interfaz (bucle de
# eventos con paradas de ~10 s: "no responde").
DISPLAY_FPS_CAP = 30.0
DEFAULT_FPS = 25.0


def find_clip(clips: list[Clip], moment: datetime) -> Clip | None:
    # Primero el clip donde la hora cae ESTRICTAMENTE antes del final: los
    # clips del DVR son contiguos (02:00-03:00, 03:00-04:00), así que una hora
    # justo en la frontera coincide con el final de uno y el inicio del
    # siguiente. El cierre inclusivo solo sirve de respaldo para la última
    # marca de un clip sin siguiente.
    for clip in clips:
        if clip.start <= moment < clip.end:
            return clip
    for clip in clips:
        if clip.start <= moment <= clip.end:
            return clip
    return None


def find_adjacent_clip(clips: list[Clip], previous_end: datetime) -> Clip | None:
    """Clip que continúa sin hueco justo después de previous_end (el DVR parte
    las grabaciones en archivos, pero para el usuario es una sola)."""
    for clip in clips:
        if clip.start <= previous_end < clip.end:
            return clip
    return None


def chunk_end_for(start: datetime, clip_end: datetime, first: bool) -> datetime:
    if first:
        end = start + timedelta(seconds=FIRST_CHUNK_SECONDS)
    else:
        end = start + timedelta(seconds=CHUNK_MIN_SECONDS)
        if end.second or end.microsecond:
            end = end.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return min(end, clip_end)


@dataclass
class PlayerDeps:
    """Lo que el reproductor necesita del resto de la app (sin Qt)."""

    store: ChunkStore
    control: PlaybackControl
    submit: Callable[[int, datetime, datetime, int, threading.Event], Future]  # canal, inicio, fin, prioridad, cancelar
    fetch_clips: Callable[[int, datetime, datetime, int], list[Clip]]  # canal, desde, hasta, prioridad
    emit_frame: Callable[[int, object], None]
    emit_status: Callable[[int, str], None]
    emit_day_changed: Callable[[date], None]


class _Request:
    """Una descarga pedida por este canal (en curso o terminada)."""

    def __init__(self, channel: int, start: datetime, end: datetime, future: Future, stop: threading.Event) -> None:
        self.channel, self.start, self.end, self.future, self.stop = channel, start, end, future, stop
        self._lock = threading.Lock()
        self._registered = False

    def register(self, store: ChunkStore) -> ChunkEntry | None:
        """Pasa el archivo descargado al almacén (una sola vez; lo llaman tanto
        quien espera la descarga como el aviso de "terminó")."""
        with self._lock:
            if self._registered:
                return store.find(self.channel, self.start)
            path: Path | None = self.future.result()
            self._registered = True
            if path is None:
                return None
            if self.stop.is_set():  # se canceló mientras terminaba: nadie lo va a usar
                path.unlink(missing_ok=True)
                return None
            return store.add(self.channel, self.start, self.end, path)


class ChannelPlayer:
    def __init__(
        self,
        channel: int,
        clips: list[Clip],
        deps: PlayerDeps,
        stop_event: threading.Event,
        semaphore: threading.Semaphore,
        is_current: Callable[[], bool],
    ) -> None:
        self.channel = channel
        # Copia propia: el adelanto del día siguiente le agrega clips, y la
        # lista original es la que usa MainWindow para dibujar la línea de tiempo.
        self.clips = list(clips)
        self.deps = deps
        self.store = deps.store
        self.control = deps.control
        self.stop_event = stop_event
        self.semaphore = semaphore
        self.is_current = is_current
        self._requests: list[_Request] = []
        self._next_day_helper: threading.Thread | None = None
        self._next_day_requested = False

    # -- ciclo de vida ------------------------------------------------------------

    def _should_stop(self) -> bool:
        return self.stop_event.is_set() or not self.is_current()

    def run(self, selected_time: datetime, start_delay: float = 0.0) -> None:
        channel = self.channel
        try:
            target = selected_time
            if start_delay > 0:
                # Al venir de vivo: los RTSP recién cerrados tardan un instante
                # en liberarse del lado del DVR (ver DVRClient.play_from).
                self.deps.emit_status(channel, f"Descargando {target:%H:%M:%S}...")
                if self.stop_event.wait(start_delay):
                    return
            while True:
                outcome, seek = self._play_from(target)
                if outcome == "stopped":
                    return
                if outcome == "seek":
                    target = seek
                    continue
                # "idle": fin de segmento o sin grabación; se queda esperando un salto.
                target = self.control.wait_seek(channel, self._should_stop)
                if target is None:
                    return
        finally:
            self._cancel_requests()
            self.control.mark_playing(channel, False)

    def _play_from(self, target: datetime) -> tuple[str, datetime | None]:
        """Reproduce desde `target` hasta el fin del segmento. Devuelve
        ("stopped"|"idle", None) o ("seek", hora) si llegó un salto fuera de lo que se reproducía."""
        channel = self.channel
        self._cancel_requests(keep_covering=target)
        clip = find_clip(self.clips, target)
        if clip is None:
            self.deps.emit_status(channel, "Sin grabación en esa hora")
            return "idle", None

        position = max(clip.start, target)
        first = True
        retries_left = MAX_CLIP_RETRIES
        while True:
            if self._should_stop():
                return "stopped", None

            outcome, entry, seek = self._acquire(clip, position, first)
            if outcome == "stopped":
                return "stopped", None
            if outcome == "seek":
                return "seek", seek
            if outcome == "ok":
                first = False
                outcome, seek = self._play_entry(clip, entry, position)
                if outcome == "stopped":
                    return "stopped", None
                if outcome == "seek":
                    return "seek", seek
            if outcome == "error":
                # Falló la descarga o el archivo salió vacío/corrupto: se
                # descarta y se reintenta el MISMO tramo antes de darlo por perdido.
                if entry is not None:
                    self.store.remove(entry)
                if retries_left <= 0:
                    self.deps.emit_status(channel, "No se pudo reproducir la grabación")
                    return "idle", None
                retries_left -= 1
                self.deps.emit_status(
                    channel, f"Reintentando descarga ({MAX_CLIP_RETRIES - retries_left}/{MAX_CLIP_RETRIES})..."
                )
                if self.stop_event.wait(CLIP_RETRY_BACKOFF):
                    return "stopped", None
                continue

            # "ended": el bloque se reprodujo completo.
            retries_left = MAX_CLIP_RETRIES
            position = entry.end
            if position < clip.end:
                continue
            outcome, next_clip = self._after_clip(clip)
            if outcome == "stopped":
                return "stopped", None
            if next_clip is None:
                self.deps.emit_status(channel, "Fin de segmento")
                return "idle", None
            if next_clip.start.date() != clip.start.date():
                self.deps.emit_day_changed(next_clip.start.date())
            clip = next_clip
            position = clip.start

    # -- obtener el bloque de una posición --------------------------------------------

    def _acquire(
        self, clip: Clip, position: datetime, first: bool
    ) -> tuple[str, ChunkEntry | None, datetime | None]:
        """("ok", bloque, None) | ("stopped"|"error", None, None) | ("seek", None, hora)."""
        channel = self.channel
        entry = self.store.find(channel, position)
        if entry is not None:
            return "ok", entry, None

        request = self._request_covering(position)
        if request is None:
            end = chunk_end_for(position, clip.end, first)
            request = self._submit(position, end, DownloadPriority.INTERACTIVE)
        if not request.future.done():
            # Solo se avisa cuando de verdad toca esperar (si ya estaba lista
            # gracias a la pre-descarga, no se nota).
            self.deps.emit_status(channel, f"Descargando {position:%H:%M:%S}...")

        while True:
            try:
                request.future.result(timeout=WAIT_POLL)
                break
            except FutureTimeout:
                pass
            if self._should_stop():
                return "stopped", None, None
            seek = self.control.take_seek(channel)
            if seek is not None:
                return "seek", None, seek

        if self._should_stop():
            return "stopped", None, None
        entry = request.register(self.store) or self.store.find(channel, position)
        if entry is None:
            # Falló: se olvida esa solicitud para que el reintento pida otra en
            # vez de quedarse esperando el mismo resultado fallido.
            if request in self._requests:
                self._requests.remove(request)
            return "error", None, None
        return "ok", entry, None

    def _request_covering(self, moment: datetime) -> _Request | None:
        for request in self._requests:
            if request.start <= moment < request.end and not request.stop.is_set():
                return request
        return None

    def _submit(self, start: datetime, end: datetime, priority: int) -> _Request:
        stop = threading.Event()
        future = self.deps.submit(self.channel, start, end, priority, stop)
        request = _Request(self.channel, start, end, future, stop)
        self._requests.append(request)
        # Pasa al almacén en cuanto termine, aunque nadie la esté esperando.
        future.add_done_callback(lambda _future, request=request: request.register(self.store))
        return request

    def _cancel_requests(self, keep_covering: datetime | None = None) -> None:
        """Cancela las descargas que ya no sirven (todas al terminar; tras un
        salto, las que no cubren el punto nuevo)."""
        remaining = []
        for request in self._requests:
            if keep_covering is not None and request.start <= keep_covering < request.end:
                remaining.append(request)
            elif not request.future.done():
                request.stop.set()
            elif keep_covering is None:
                request.stop.set()
        self._requests = remaining

    # -- reproducir un bloque ---------------------------------------------------------------

    def _play_entry(self, clip: Clip, entry: ChunkEntry, position: datetime) -> tuple[str, datetime | None]:
        """("ended"|"stopped"|"error", None) o ("seek", hora) si el salto cae fuera de este bloque."""
        channel, control = self.channel, self.control
        capture = cv2.VideoCapture(str(entry.path), cv2.CAP_FFMPEG)
        try:
            if not capture.isOpened():
                return "error", None
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0 or fps == float("inf"):
                fps = DEFAULT_FPS
            interval = 1.0 / fps

            def frame_at(moment: datetime) -> int:
                return max(0, round((moment - entry.start).total_seconds() * fps))

            if position > entry.start:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_at(position))

            self._on_chunk_start(clip, entry, position)
            control.mark_playing(channel, True)
            self.deps.emit_status(channel, control.status_text())

            next_frame_at = time.monotonic()
            seen_epoch = control.epoch
            credit = 1.0  # cuadros "por pintar" acumulados (ver DISPLAY_FPS_CAP)
            frames_read = 0
            did_seek = False
            while True:
                if self._should_stop():
                    return "stopped", None

                # Pausa compartida: espera aquí (sin tocar el DVR) hasta reanudar, o deja pasar un cuadro suelto.
                turn = control.wait_turn(channel, self._should_stop)
                if turn == "stop":
                    return "stopped", None

                rebase = turn == "step"
                seek = control.take_seek(channel)
                if seek is not None:
                    if not (entry.start <= seek < entry.end):
                        return "seek", seek
                    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_at(seek))
                    credit = 1.0
                    rebase = True
                    did_seek = True

                if rebase or control.epoch != seen_epoch:
                    seen_epoch = control.epoch
                    next_frame_at = time.monotonic()

                now = time.monotonic()
                if turn != "step" and now < next_frame_at:
                    time.sleep(next_frame_at - now)

                speed = control.speed
                paint = True
                if turn != "step" and speed * fps > DISPLAY_FPS_CAP * (1 + 1e-9) and speed > 1.0:
                    credit += 1.0 / speed
                    paint = credit >= 1.0 - 1e-9
                    if paint:
                        credit -= 1.0
                if paint:
                    ok, frame = capture.read()
                else:
                    ok, frame = capture.grab(), None
                if not ok:
                    break
                frames_read += 1
                if paint:
                    # Backpressure: aquí NUNCA se descarta un cuadro ya
                    # decodificado -- se espera a que la interfaz confirme haber
                    # consumido uno anterior (DVRClient.notify_recording_frame_consumed).
                    while not self.semaphore.acquire(timeout=BACKPRESSURE_POLL):
                        if self._should_stop():
                            return "stopped", None
                    self.deps.emit_frame(channel, frame)
                next_frame_at = max(next_frame_at + interval / control.speed, time.monotonic())
            return ("ended", None) if frames_read > 0 or did_seek else ("error", None)
        finally:
            capture.release()
            control.mark_playing(channel, False)

    # -- adelantos --------------------------------------------------------------------------

    def _on_chunk_start(self, clip: Clip, entry: ChunkEntry, position: datetime) -> None:
        self.store.prune(self.channel, position - KEEP_BEHIND, position + KEEP_AHEAD)
        self._prefetch_next(clip, entry)
        self._prefetch_previous(clip, entry)

    def _prefetch_next(self, clip: Clip, entry: ChunkEntry) -> None:
        if entry.end < clip.end:
            start, end = entry.end, chunk_end_for(entry.end, clip.end, False)
        else:
            adjacent = find_adjacent_clip(self.clips, clip.end)
            if adjacent is not None:
                start, end = adjacent.start, chunk_end_for(adjacent.start, adjacent.end, False)
            elif clip.end.time() == datetime.min.time() and not self._next_day_requested:
                # Último clip del día y no se conoce nada después: puede que la
                # grabación siga en el día siguiente.
                self._next_day_requested = True
                self._next_day_helper = threading.Thread(
                    target=self._prefetch_next_day, args=(clip, entry), daemon=True
                )
                self._next_day_helper.start()
                return
            else:
                return
        if self.store.find(self.channel, start) is None and self._request_covering(start) is None:
            self._submit(start, end, DownloadPriority.PREFETCH)

    def _prefetch_previous(self, clip: Clip, entry: ChunkEntry) -> None:
        """Lo de atrás, hasta el minuto anterior, para que retroceder sea instantáneo."""
        if entry.start <= clip.start:
            return
        boundary = entry.start.replace(second=0, microsecond=0)
        if boundary == entry.start:
            boundary -= timedelta(minutes=1)
        start = max(clip.start, boundary)
        probe = entry.start - timedelta(seconds=1)
        if self.store.find(self.channel, probe) is None and self._request_covering(probe) is None:
            self._submit(start, entry.start, DownloadPriority.BACKGROUND)

    def _prefetch_next_day(self, clip: Clip, entry: ChunkEntry) -> None:
        """Hilo aparte: pide los clips del día que sigue y, con ellos, adelanta su primer bloque."""
        day_start = clip.end
        try:
            fetched = self.deps.fetch_clips(
                self.channel, day_start, day_start + timedelta(hours=23, minutes=59, seconds=59), LightPriority.PERIODIC
            )
        except Exception:
            return  # sin clips del día siguiente: se cae al "Fin de segmento" de siempre
        if self._should_stop():
            return
        self.clips.extend(fetched)
        self._prefetch_next(clip, entry)

    def _after_clip(self, clip: Clip) -> tuple[str, Clip | None]:
        next_clip = find_adjacent_clip(self.clips, clip.end)
        helper = self._next_day_helper
        if next_clip is None and helper is not None:
            # Todavía se estaban pidiendo los clips del día siguiente
            # (normalmente ya terminó: tuvo todo el último clip).
            while helper.is_alive():
                if self._should_stop():
                    return "stopped", None
                helper.join(WAIT_POLL)
            next_clip = find_adjacent_clip(self.clips, clip.end)
        return "next", next_clip
