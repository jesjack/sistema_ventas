from __future__ import annotations

import math
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
from .playback_control import SYNC_STATUS, PlaybackControl

# Reproductor de UN canal de grabaciones. Corre en su propio hilo y sirve el
# video desde el almacén local de bloques (chunk_store.py): solo descarga del
# DVR (por el embudo) lo que el almacén no tiene, y mientras reproduce trae
# por adelantado los bloques vecinos -- así el siguiente, el anterior y los
# saltos de ±10 s ya están en disco cuando se piden. Un salto NO reinicia el
# hilo: llega como una orden por PlaybackControl. Lo mismo el sentido
# (normal/reversa) y la velocidad.
#
# Reglas de bloques (en reversa se miran en espejo):
#   - el primer bloque tras un salto a un punto NO descargado es corto (15 s),
#     para ver imagen pronto;
#   - los siguientes terminan (o, en reversa, empiezan) en el primer minuto
#     exacto que quede a más de 20 s (duran de 20 a 80 s, y 60 s ya alineados);
#   - tras empezar un bloque se pide el vecino hacia donde se va (PREFETCH) y
#     el del otro lado (BACKGROUND).
#
# Reversa: H.264 no se decodifica hacia atrás, pero el DVR pone un cuadro
# clave por segundo y OpenCV salta a cualquier cuadro con precisión exacta, así
# que se decodifica hacia adelante un bloquecito (REVERSE_BLOCK_FRAMES) y se
# muestra al revés, y luego el bloquecito anterior.

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
# Cuadros por bloque en la reversa. Cada salto de OpenCV decodifica desde el cuadro
# clave anterior (~15 cuadros de sobra), así que con bloques chicos ese costo
# domina: medido con los 4 canales a la vez, 12 cuadros -> 36 cuadros/s por canal,
# 20 -> 58-67, 30 -> 70-80 (avanzar: 95-109). Mientras se muestra un bloque el
# siguiente se va decodificando POCO A POCO en el mismo hilo (un par de cuadros por
# cada cuadro mostrado): con un solo bloque decodificado de golpe la imagen se
# frenaba ~0.4 s cada segundo (25 cuadros/s pintados a x1), y con un hilo auxiliar la
# interfaz sufría tirones de hasta segundos por la competencia de CPU. Memoria:
# ~2 bloques x 3 MB x 30 cuadros ≈ 180 MB por canal (~700 MB entre los 4) solo en reversa.
REVERSE_BLOCK_FRAMES = 30
EPSILON = timedelta(milliseconds=1)
# Sincronía con el reloj compartido (ver playback_control.py): un cuadro que va más
# atrasado que LATE_SKIP segundos no se pinta (se decodifica y se descarta, para
# alcanzar al reloj); si el atraso pasa de LATE_SEEK (p. ej. se esperó una descarga)
# se salta directo a la hora actual del reloj.
LATE_SKIP = 0.12
LATE_SEEK = 1.5
PACE_STEP = 0.03


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


def find_previous_clip(clips: list[Clip], next_start: datetime) -> Clip | None:
    """Clip que termina justo donde empieza el que se está reproduciendo."""
    for clip in clips:
        if clip.start < next_start <= clip.end:
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


def chunk_start_for(end: datetime, clip_start: datetime, first: bool) -> datetime:
    """Espejo de chunk_end_for: el inicio de un bloque que termina en `end`."""
    if first:
        start = end - timedelta(seconds=FIRST_CHUNK_SECONDS)
    else:
        start = end - timedelta(seconds=CHUNK_MIN_SECONDS)
        start = start.replace(second=0, microsecond=0)
    return max(start, clip_start)


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


class _NextBlock:
    """El bloque que sigue en reversa, decodificándose de a poco."""

    def __init__(self, low: int, high: int, flags: dict[int, bool]) -> None:
        self.low, self.high, self.flags = low, high, flags
        self.cursor = low
        self.frames: list[tuple[int, object]] = []
        self.positioned = False


class _ChunkReader:
    """Lee los cuadros de un bloque en cualquiera de los dos sentidos.

    En avance lee en secuencia. En reversa decodifica hacia adelante un bloque de
    REVERSE_BLOCK_FRAMES (saltando con `set` por número de cuadro) y lo entrega del
    último al primero; mientras tanto va decodificando el bloque anterior a razón
    de unos pocos cuadros por cada cuadro mostrado. `next_index` es el índice del
    próximo cuadro que se va a mostrar."""

    def __init__(self, capture: cv2.VideoCapture, expected_frames: int, path: str = "") -> None:
        self.capture = capture
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        self.total = int(count) if count and 0 < count < 1e7 else expected_frames
        self.reverse = False
        self.next_index = 0
        self._block: list[tuple[int, object]] = []  # ascendente; el siguiente a mostrar es el último
        self._next: _NextBlock | None = None
        # En reversa, qué cuadros se convierten a imagen (los demás solo se decodifican):
        # a velocidad alta se pintan ~30 por segundo (DISPLAY_FPS_CAP).
        self.paint_ratio = 1.0
        self._paint_credit = 1.0

    def seek(self, index: int) -> None:
        """Muestra `index` a continuación."""
        self.next_index = max(0, min(index, self.total - 1))
        self._reset_reverse_state()
        if not self.reverse:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, self.next_index)

    def set_reverse(self, reverse: bool) -> None:
        if reverse == self.reverse:
            return
        last_shown = self.next_index + (1 if self.reverse else -1)
        self.reverse = reverse
        self._reset_reverse_state()
        self.next_index = last_shown + (-1 if reverse else 1)
        if not reverse and 0 <= self.next_index < self.total:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, self.next_index)

    def _reset_reverse_state(self) -> None:
        self._block = []
        self._next = None
        self._paint_credit = 1.0

    def read(self, paint: bool) -> tuple[bool, object | None]:
        """(ok, cuadro). El cuadro es None cuando no hay que pintarlo (en avance lo
        decide `paint`; en reversa, `paint_ratio`)."""
        if not self.reverse:
            if self.next_index >= self.total:
                return False, None
            ok, frame = self.capture.read() if paint else (self.capture.grab(), None)
            if ok:
                self.next_index += 1
            return ok, frame
        if self.next_index < 0:
            return False, None
        if not self._block:
            self._load_block()
            if not self._block:
                return False, None
        index, frame = self._block.pop()
        self.next_index = index - 1
        self._decode_some_of_next()
        return True, frame

    def close(self) -> None:
        self._reset_reverse_state()

    # -- reversa: bloques ----------------------------------------------------------------

    def _paint_flags(self, low: int, high: int) -> dict[int, bool]:
        """Qué cuadros de [low, high] se pintan, contando en el orden en que se muestran (de high a low)."""
        flags = {}
        credit = self._paint_credit
        for index in range(high, low - 1, -1):
            credit += self.paint_ratio
            flags[index] = credit >= 1.0 - 1e-9
            if flags[index]:
                credit -= 1.0
        self._paint_credit = credit
        return flags

    def _decode_frames(self, block: _NextBlock, count: int) -> None:
        """Decodifica hasta `count` cuadros más del bloque (con un solo salto al empezar)."""
        if not block.positioned:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, block.low)
            block.positioned = True
        for _ in range(count):
            if block.cursor > block.high:
                return
            if block.flags[block.cursor]:
                ok, frame = self.capture.read()
            else:
                ok, frame = self.capture.grab(), None
            if not ok:
                block.high = block.cursor - 1  # el archivo terminó antes de lo esperado
                return
            block.frames.append((block.cursor, frame))
            block.cursor += 1

    def _load_block(self) -> None:
        high = min(self.next_index, self.total - 1)
        low = max(0, high - REVERSE_BLOCK_FRAMES + 1)
        block = self._next
        if block is None or (block.low, block.high) != (low, high):
            block = _NextBlock(low, high, self._paint_flags(low, high))
        self._decode_frames(block, block.high - block.cursor + 1)  # lo que falte, de una vez
        self._block = block.frames
        self._next = None
        if self._block and low > 0:
            next_low, next_high = max(0, low - REVERSE_BLOCK_FRAMES), low - 1
            self._next = _NextBlock(next_low, next_high, self._paint_flags(next_low, next_high))

    def _decode_some_of_next(self) -> None:
        """Adelanta el bloque siguiente repartiendo lo que falta entre los cuadros que quedan por mostrar."""
        block = self._next
        if block is None or block.cursor > block.high:
            return
        remaining_ticks = len(self._block) + 1
        self._decode_frames(block, math.ceil((block.high - block.cursor + 1) / remaining_ticks))


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
                # "idle": fin/inicio de segmento o sin grabación; no hace esperar a los
                # demás canales y espera un salto.
                self.control.announce_absent(channel)
                target = self.control.wait_seek(channel, self._should_stop)
                if target is None:
                    return
        finally:
            self._cancel_requests()
            self.control.mark_playing(channel, False)

    def _play_from(self, target: datetime) -> tuple[str, datetime | None]:
        """Reproduce desde `target` hasta el fin (o, en reversa, el inicio) del
        segmento. Devuelve ("stopped"|"idle", None) o ("seek", hora) si llegó un
        salto fuera de lo que se reproducía."""
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
            reverse = self.control.reverse

            outcome, entry, seek = self._acquire(clip, position, first, reverse)
            if outcome == "stopped":
                return "stopped", None
            if outcome == "seek":
                return "seek", seek
            if outcome == "ok":
                first = False
                outcome, seek = self._play_entry(clip, entry, position, reverse)
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

            retries_left = MAX_CLIP_RETRIES
            if outcome == "ended":  # el bloque se reprodujo completo hacia adelante
                position = entry.end
                if position < clip.end:
                    continue
                outcome, next_clip = self._after_clip(clip)
                if outcome == "stopped":
                    return "stopped", None
                if next_clip is None:
                    self.deps.emit_status(channel, "Fin de segmento")
                    return "idle", None
                position_after = next_clip.start
            else:  # "ended_reverse": el bloque se reprodujo completo hacia atrás
                position = entry.start
                if position > clip.start:
                    continue
                next_clip = find_previous_clip(self.clips, clip.start)
                if next_clip is None:
                    self.deps.emit_status(channel, "Inicio de segmento")
                    return "idle", None
                position_after = next_clip.end
            if next_clip.start.date() != clip.start.date():
                self.deps.emit_day_changed(next_clip.start.date())
            clip = next_clip
            position = position_after

    # -- obtener el bloque de una posición --------------------------------------------

    def _acquire(
        self, clip: Clip, position: datetime, first: bool, reverse: bool
    ) -> tuple[str, ChunkEntry | None, datetime | None]:
        """("ok", bloque, None) | ("stopped"|"error", None, None) | ("seek", None, hora).

        En reversa se busca lo que hay JUSTO ANTES de `position` (un bloque
        cubre [inicio, fin): la frontera pertenece al bloque de después)."""
        channel = self.channel
        probe = position - EPSILON if reverse else position
        entry = self.store.find(channel, probe)
        if entry is not None:
            return "ok", entry, None

        request = self._request_covering(probe)
        if request is None:
            if reverse:
                end = min(position, clip.end)
                start = chunk_start_for(end, clip.start, first)
            else:
                start = position
                end = chunk_end_for(position, clip.end, first)
            request = self._submit(start, end, DownloadPriority.INTERACTIVE)
        if not request.future.done():
            # Solo se avisa cuando de verdad toca esperar (si ya estaba lista
            # gracias a la pre-descarga, no se nota).
            self.deps.emit_status(channel, f"Descargando {request.start:%H:%M:%S}...")

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
        entry = request.register(self.store) or self.store.find(channel, probe)
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

    def _play_entry(
        self, clip: Clip, entry: ChunkEntry, position: datetime, reverse: bool
    ) -> tuple[str, datetime | None]:
        """("ended"|"ended_reverse"|"stopped"|"error", None) o ("seek", hora) si el
        salto cae fuera de este bloque."""
        channel, control = self.channel, self.control
        capture = cv2.VideoCapture(str(entry.path), cv2.CAP_FFMPEG)
        reader: _ChunkReader | None = None
        try:
            if not capture.isOpened():
                return "error", None
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0 or fps == float("inf"):
                fps = DEFAULT_FPS
            expected = max(1, round((entry.end - entry.start).total_seconds() * fps))
            reader = _ChunkReader(capture, expected)
            reader.reverse = reverse

            def frame_at(moment: datetime) -> int:
                return max(0, round((moment - entry.start).total_seconds() * fps))

            if reverse:
                # Entrando desde el bloque de después (frontera): empieza por el último cuadro.
                reader.seek(reader.total - 1 if position >= entry.end else frame_at(position))
            elif position > entry.start:
                reader.seek(frame_at(position))

            self._on_chunk_start(clip, entry, position)
            control.mark_playing(channel, True)
            control.announce_ready(channel)  # barrera de arranque: ya tengo dónde empezar
            waiting_for_others = control.has_clock() and not control.clock_running() and not control.paused
            self.deps.emit_status(channel, SYNC_STATUS if waiting_for_others else control.status_text())

            credit = 1.0  # cuadros "por pintar" acumulados (ver DISPLAY_FPS_CAP)
            frames_read = 0
            progressed = False
            while True:
                if self._should_stop():
                    return "stopped", None

                # Pausa/arranque compartidos: espera aquí (sin tocar el DVR) a que el reloj corra,
                # o a un permiso de cuadro suelto si está en pausa.
                turn = control.wait_turn(channel, self._should_stop)
                if turn == "stop":
                    return "stopped", None
                if waiting_for_others:
                    waiting_for_others = False
                    self.deps.emit_status(channel, control.status_text())

                seek = control.take_seek(channel)
                if seek is not None:
                    if not (entry.start <= seek < entry.end):
                        return "seek", seek  # (en pausa el permiso de cuadro queda para el bloque nuevo)
                    reader.seek(frame_at(seek))
                    credit = 1.0
                    progressed = True
                    control.announce_ready(channel)  # el salto rearmó la barrera
                    waiting_for_others = control.has_clock() and not control.clock_running() and not control.paused
                    if waiting_for_others:
                        self.deps.emit_status(channel, SYNC_STATUS)
                    continue

                if control.reverse != reader.reverse:
                    reader.set_reverse(control.reverse)
                    credit = 1.0
                    progressed = True

                # Ritmo: este cuadro se muestra cuando el reloj compartido llegue a su hora de video.
                late = 0.0
                if turn != "step" and control.has_clock():
                    media = entry.start + timedelta(seconds=reader.next_index / fps)
                    resync = False
                    while True:
                        if self._should_stop():
                            return "stopped", None
                        if (
                            control.peek_seek(channel) is not None
                            or control.paused
                            or not control.clock_running()
                            or control.reverse != reader.reverse
                        ):
                            resync = True  # cambió algo (salto, pausa, sentido): se reevalúa desde arriba
                            break
                        delta = control.wall_for(media) - time.monotonic()
                        if delta <= 0:
                            late = -delta
                            break
                        time.sleep(min(delta, PACE_STEP))
                    if resync:
                        continue
                    if late > LATE_SEEK:
                        target = control.media_now()
                        if target is not None:
                            if not (entry.start <= target < entry.end):
                                return "seek", target
                            reader.seek(frame_at(target))
                            credit = 1.0
                            continue

                speed = control.speed
                capped = turn != "step" and speed > 1.0 and speed * fps > DISPLAY_FPS_CAP * (1 + 1e-9)
                paint = True
                if reader.reverse:
                    reader.paint_ratio = 1.0 / speed if capped else 1.0  # en reversa el lector decide qué cuadros convierte
                elif late > LATE_SKIP:
                    paint = False  # atrasado: se decodifica sin pintar para alcanzar al reloj
                elif capped:
                    credit += 1.0 / speed
                    paint = credit >= 1.0 - 1e-9
                    if paint:
                        credit -= 1.0
                ok, frame = reader.read(paint)
                if not ok:
                    break
                frames_read += 1
                if reader.reverse:
                    paint = frame is not None and late <= LATE_SKIP
                if paint:
                    # Backpressure: aquí NUNCA se descarta un cuadro ya decodificado por
                    # falta de turno -- se espera a que la interfaz confirme haber
                    # consumido uno anterior (DVRClient.notify_recording_frame_consumed).
                    while not self.semaphore.acquire(timeout=BACKPRESSURE_POLL):
                        if self._should_stop():
                            return "stopped", None
                    self.deps.emit_frame(channel, frame)
            if frames_read == 0 and not progressed:
                return "error", None
            return ("ended_reverse" if reader.reverse else "ended"), None
        finally:
            if reader is not None:
                reader.close()
            capture.release()
            control.mark_playing(channel, False)

    # -- adelantos --------------------------------------------------------------------------

    def _on_chunk_start(self, clip: Clip, entry: ChunkEntry, position: datetime) -> None:
        self.store.prune(self.channel, position - KEEP_BEHIND, position + KEEP_AHEAD)
        self._prefetch_neighbours(clip, entry)

    def _prefetch_neighbours(self, clip: Clip, entry: ChunkEntry) -> None:
        if self.control.reverse:
            self._prefetch_previous(clip, entry, DownloadPriority.PREFETCH, long_chunk=True)
            self._prefetch_next(clip, entry, DownloadPriority.BACKGROUND)
        else:
            self._prefetch_next(clip, entry, DownloadPriority.PREFETCH)
            self._prefetch_previous(clip, entry, DownloadPriority.BACKGROUND, long_chunk=False)

    def _prefetch_next(self, clip: Clip, entry: ChunkEntry, priority: int) -> None:
        if entry.end < clip.end:
            start, end = entry.end, chunk_end_for(entry.end, clip.end, False)
        else:
            adjacent = find_adjacent_clip(self.clips, clip.end)
            if adjacent is not None:
                start, end = adjacent.start, chunk_end_for(adjacent.start, adjacent.end, False)
            elif (
                priority == DownloadPriority.PREFETCH
                and clip.end.time() == datetime.min.time()
                and not self._next_day_requested
            ):
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
            self._submit(start, end, priority)

    def _prefetch_previous(self, clip: Clip, entry: ChunkEntry, priority: int, long_chunk: bool) -> None:
        """Lo de atrás. En avance (BACKGROUND) solo hasta el minuto anterior, para que
        retroceder sea instantáneo; en reversa (PREFETCH) un bloque completo, y cruzando
        al clip anterior si este ya no tiene más atrás."""
        if entry.start <= clip.start:
            previous = find_previous_clip(self.clips, clip.start) if long_chunk else None
            if previous is None:
                return
            start, end = chunk_start_for(previous.end, previous.start, False), previous.end
        elif long_chunk:
            start, end = chunk_start_for(entry.start, clip.start, False), entry.start
        else:
            boundary = entry.start.replace(second=0, microsecond=0)
            if boundary == entry.start:
                boundary -= timedelta(minutes=1)
            start, end = max(clip.start, boundary), entry.start
        probe = end - timedelta(seconds=1)
        if self.store.find(self.channel, probe) is None and self._request_covering(probe) is None:
            self._submit(start, end, priority)

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
        self._prefetch_next(clip, entry, DownloadPriority.PREFETCH)

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
