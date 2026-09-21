from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import cv2

from . import download_client
from .clip import Clip
from .download_manager import DownloadPriority
from .export_clip import (
    CANCELLED_TEXT,
    WAIT_POLL,
    ClipRange,
    ExportError,
    estimate_bytes,
    find_ffmpeg,
    make_folder,
    own_as_user,
    unique_path,
)

# Exportar HORAS (o el día entero) de uno o varios canales: un archivo MP4 por canal con las horas
# elegidas una tras otra. Sin Qt: la interfaz lanza start_hours_export() y lee `events` con un
# temporizador (los hilos NUNCA referencian widgets, ver la nota de dvr_info_dialog.py).
#
# Cómo se hace (todo medido en el DVR real el 2026-09-21, ver NOTAS.md):
#  - Cada canal se pide en TROZOS de CHUNK_SECONDS por el embudo con la prioridad más baja
#    (BACKGROUND) y UNO SOLO en vuelo: así siempre queda libre uno de los 2 cupos del DVR para
#    la reproducción y para los clips cortos, y la vista en vivo (que espera a que terminen las
#    descargas en curso) no espera más que un trozo. Un solo flujo baja ≈ 36 veces el tiempo real.
#  - Los trozos consecutivos del DVR encajan al fotograma (duran justo lo pedido, empiezan en un
#    fotograma clave, sin solapes ni huecos), así que se reempaquetan a MPEG-TS (sin recodificar) y
#    se unen con `ffmpeg -c copy`.
#  - Donde no hubo grabación (o un trozo no se pudo bajar) se mete un tramo NEGRO con
#    "Grabación no disponible" y la hora supuesta avanzando cada segundo (ffmpeg drawtext, 1 fps,
#    de la misma resolución que el video real).
#  - Un fallo o una cancelación en un canal nunca borra los canales ya terminados.

CHUNK_SECONDS = 120.0
GAP_TOLERANCE = 2.0  # s: un hueco menor que esto entre grabaciones no cuenta (no se rellena)
MIN_PIECE = 1.0
MAX_GAP_PIECE = 1800.0  # s: un hueco largo se parte en varios tramos negros (avance y cancelación más finos)
CHUNK_RETRIES = 2  # reintentos de un trozo antes de darlo por perdido (se rellena con negro y se avisa)
CHUNK_RETRY_DELAYS = (2.0, 5.0)
STATS_POLL_SECONDS = 2.0  # cada cuánto se mira si hay una vista en vivo abierta (el embudo la pausa sola)
DEFAULT_SIZE = (1280, 720)
GAP_TEXT = "Grabación no disponible"
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
FFMPEG_STEP_TIMEOUT = 3600.0  # la unión final de un canal de muchas horas puede tardar minutos
VERIFY_TOLERANCE_SECONDS = 5.0

PHASE_WAITING = "waiting"
PHASE_DOWNLOADING = "downloading"
PHASE_GAPS = "gaps"  # preparando los tramos negros
PHASE_JOINING = "joining"  # uniendo todo en el MP4 final


class _Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Piece:
    kind: str  # "video" (se descarga) | "gap" (tramo negro)
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass
class HoursSpec:
    day: date
    cells: dict[int, list[int]]  # canal -> horas elegidas (0-23)
    folder: Path
    clips: dict[int, list[Clip]]  # las grabaciones de ese día por canal (para saber dónde hay huecos)
    now: datetime

    def channels(self) -> list[int]:
        return sorted(channel for channel, hours in self.cells.items() if hours)


# -- plan ------------------------------------------------------------------------------------------


def merge_intervals(clips: Iterable[Clip], tolerance: float = GAP_TOLERANCE) -> list[tuple[datetime, datetime]]:
    """Las grabaciones de un canal como intervalos disjuntos (los huecos < `tolerance` se ignoran)."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted((clip.start, clip.end) for clip in clips):
        if merged and (start - merged[-1][1]).total_seconds() <= tolerance:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def hour_blocks(day: date, hours: Iterable[int], limit: datetime | None = None) -> list[tuple[datetime, datetime]]:
    """Las horas elegidas como bloques continuos [inicio, fin). `limit` (p. ej. la última grabación
    conocida) recorta el final: no hay nada más allá."""
    blocks: list[tuple[datetime, datetime]] = []
    midnight = datetime.combine(day, dtime.min)
    for hour in sorted(set(hours)):
        start, end = midnight + timedelta(hours=hour), midnight + timedelta(hours=hour + 1)
        if blocks and blocks[-1][1] == start:
            blocks[-1] = (blocks[-1][0], end)
        else:
            blocks.append((start, end))
    if limit is not None:
        blocks = [(start, min(end, limit)) for start, end in blocks if start < limit]
    return [(start, end) for start, end in blocks if (end - start).total_seconds() >= MIN_PIECE]


def build_pieces(
    blocks: list[tuple[datetime, datetime]],
    recorded: list[tuple[datetime, datetime]],
    chunk_seconds: float = CHUNK_SECONDS,
) -> list[Piece]:
    """Las piezas del archivo de un canal, en orden: trozos de video de ≤ chunk_seconds donde hubo
    grabación y tramos negros donde no."""
    pieces: list[Piece] = []
    chunk = timedelta(seconds=chunk_seconds)
    for block_start, block_end in blocks:
        cursor = block_start
        for rec_start, rec_end in recorded:
            start, end = max(rec_start, block_start), min(rec_end, block_end)
            if (end - start).total_seconds() < MIN_PIECE:
                continue
            _add_gap(pieces, cursor, start)
            moment = start
            while moment < end:
                following = min(moment + chunk, end)
                if (end - following).total_seconds() < MIN_PIECE:  # un resto minúsculo se pega al trozo
                    following = end
                pieces.append(Piece("video", moment, following))
                moment = following
            cursor = max(cursor, end)
        _add_gap(pieces, cursor, block_end)
    return pieces


def _add_gap(pieces: list[Piece], start: datetime, end: datetime) -> None:
    if (end - start).total_seconds() < GAP_TOLERANCE:
        return
    step = timedelta(seconds=MAX_GAP_PIECE)
    moment = start
    while moment < end:
        following = min(moment + step, end)
        pieces.append(Piece("gap", moment, following))
        moment = following


def channel_pieces(spec: HoursSpec, channel: int, chunk_seconds: float = CHUNK_SECONDS) -> list[Piece]:
    recorded = merge_intervals(spec.clips.get(channel, []))
    if not recorded:
        return []
    limit = min(spec.now, recorded[-1][1])  # más allá de la última grabación conocida no hay "hueco", solo nada aún
    return build_pieces(hour_blocks(spec.day, spec.cells.get(channel, []), limit), recorded, chunk_seconds)


def hour_has_recording(clips: Iterable[Clip], day: date, hour: int, now: datetime | None = None) -> bool:
    start = datetime.combine(day, dtime.min) + timedelta(hours=hour)
    end = start + timedelta(hours=1)
    if now is not None:
        end = min(end, now)
    return any(min(clip.end, end) - max(clip.start, start) >= timedelta(seconds=MIN_PIECE) for clip in clips)


@dataclass(frozen=True)
class ChannelPlan:
    channel: int
    pieces: tuple[Piece, ...]

    @property
    def video_seconds(self) -> float:
        return sum(piece.seconds for piece in self.pieces if piece.kind == "video")

    @property
    def gap_seconds(self) -> float:
        return sum(piece.seconds for piece in self.pieces if piece.kind == "gap")

    @property
    def total_seconds(self) -> float:
        return self.video_seconds + self.gap_seconds

    @property
    def estimated_bytes(self) -> float:
        return sum(estimate_bytes(ClipRange(p.start, p.end), 1) for p in self.pieces if p.kind == "video")


def plan(spec: HoursSpec, chunk_seconds: float = CHUNK_SECONDS) -> list[ChannelPlan]:
    return [ChannelPlan(channel, tuple(channel_pieces(spec, channel, chunk_seconds))) for channel in spec.channels()]


def output_name(channel: int, day: date, hours: Iterable[int]) -> str:
    """CAM1_2026-09-20_08h-11h.mp4 (varios bloques: 08h-09h_14h-17h)."""
    blocks = [(s.hour, e.hour if e.day == s.day else 24) for s, e in hour_blocks(day, hours)]
    if len(blocks) > 3:
        label = f"{blocks[0][0]:02d}h-{blocks[-1][1]:02d}h_{len(blocks)}-bloques"
    else:
        label = "_".join(f"{start:02d}h-{end:02d}h" for start, end in blocks) or "sin-horas"
    return f"CAM{channel}_{day:%Y-%m-%d}_{label}.mp4"


def find_font() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


# -- ffmpeg ----------------------------------------------------------------------------------------


def gap_command(ffmpeg: str, font: str | None, output: Path, size: tuple[int, int], start: datetime, seconds: float) -> list[str]:
    """Un tramo negro de `seconds` s, a 1 cuadro por segundo, con el aviso y la hora supuesta
    (`start` + los segundos transcurridos) al centro, en MPEG-TS con la misma resolución del canal."""
    width, height = size
    source = f"color=c=black:s={width}x{height}:r=1:d={seconds:.3f}"
    command = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", source]
    if font:
        epoch = int(start.timestamp())
        clock = "%{pts\\:localtime\\:" + str(epoch) + "\\:%H\\\\\\:%M\\\\\\:%S}"  # los ':' del formato, escapados dos veces
        command += [
            "-vf",
            f"drawtext=fontfile={font}:text='{GAP_TEXT}':fontcolor=white:fontsize={max(12, height // 22)}"
            f":x=(w-tw)/2:y=(h/2)-{height // 12},"
            f"drawtext=fontfile={font}:text='{clock}':fontcolor=white:fontsize={max(14, height // 14)}"
            f":x=(w-tw)/2:y=(h/2)+{height // 40}",
        ]
    command += [
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-f", "mpegts", str(output),
    ]
    return command


def video_size(path: Path) -> tuple[int, int] | None:
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()
    return (width, height) if width > 0 and height > 0 else None


def _run_ffmpeg(command: list[str], stop: threading.Event, timeout: float = FFMPEG_STEP_TIMEOUT) -> None:
    """Corre ffmpeg y lo mata si se cancela. Lanza ExportError si falla."""
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        raise ExportError(f"No se pudo ejecutar ffmpeg: {exc}") from exc
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if stop.wait(0.2):
                process.kill()
                process.wait()
                raise _Cancelled()
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise ExportError("ffmpeg tardó demasiado")
        stderr = process.stderr.read() if process.stderr else ""
    finally:
        if process.stderr:
            process.stderr.close()
    if process.returncode != 0:
        raise ExportError(f"ffmpeg falló: {stderr.strip()[-200:] or process.returncode}")


def media_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def verify_output(path: Path, expected_seconds: float) -> str | None:
    """Comprueba que el archivo abre y tiene imagen; devuelve un AVISO si su duración se aparta de lo
    esperado, y lanza ExportError si no sirve."""
    if not path.exists() or path.stat().st_size == 0:
        raise ExportError("El archivo quedó vacío")
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        if not capture.isOpened():
            raise ExportError("El archivo guardado no se puede abrir")
        ok, _ = capture.read()
        if not ok:
            raise ExportError("El archivo guardado no tiene imagen")
    finally:
        capture.release()
    duration = media_duration(path)
    if duration is not None and abs(duration - expected_seconds) > max(VERIFY_TOLERANCE_SECONDS, expected_seconds * 0.01):
        return f"dura {duration:.0f} s en vez de los {expected_seconds:.0f} s esperados"
    return None


# -- ejecución -------------------------------------------------------------------------------------


class HoursExport:
    """Exportación en curso: `events` (cola) y `cancel()`.

    Avisos en `events`, siempre tuplas:
      ("plan", canal, piezas, segundos_totales, segundos_de_video, segundos_negros)
      ("piece", canal, indice, inicio, fin)          empieza a bajarse ese trozo (índice en las piezas)
      ("progress", canal, indice, bytes)             bytes recibidos de ese trozo
      ("piece_done", canal, indice)
      ("state", canal, texto, fase)                  fase: PHASE_*
      ("warning", canal, texto)                      p. ej. un trozo que no se pudo bajar
      ("paused", bool)                               hay una vista en vivo abierta: el embudo pausó las descargas
      ("channel_done", canal, ruta, aviso|None)
      ("channel_failed", canal, mensaje)
      ("finished", {canal: ruta|None})               terminó todo (nunca falta este aviso)"""

    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def cancel(self) -> None:
        self.stop.set()

    def finished(self) -> bool:
        return self.thread is not None and not self.thread.is_alive()


def start_hours_export(
    host: str,
    username: str,
    password: str,
    spec: HoursSpec,
    submit: Callable[..., Future] | None = None,
    ffmpeg: str | None = None,
    stats: Callable[[], dict | None] | None = None,
    chunk_seconds: float = CHUNK_SECONDS,
    work_root: Path | None = None,
) -> HoursExport:
    handle = HoursExport()
    handle.thread = threading.Thread(
        target=_run_hours_export,
        args=(handle, host, username, password, spec, submit or download_client.submit, ffmpeg or find_ffmpeg(),
              stats or download_client.stats, chunk_seconds, work_root),
        name="HoursExport",
        daemon=True,
    )
    handle.thread.start()
    return handle


def _run_hours_export(handle, host, username, password, spec, submit, ffmpeg, stats, chunk_seconds, work_root) -> None:
    events = handle.events
    channels = spec.channels()
    results: dict[int, str | None] = {channel: None for channel in channels}
    try:
        if not ffmpeg:
            for channel in channels:
                events.put(("channel_failed", channel, "Hace falta ffmpeg para exportar horas (no está instalado)"))
            return
        make_folder(spec.folder)
        for channel in channels:
            if handle.stop.is_set():
                events.put(("channel_failed", channel, CANCELLED_TEXT))
                continue
            try:
                worker = _ChannelExport(handle, host, username, password, spec, channel, submit, ffmpeg, stats, chunk_seconds, work_root)
                path, warning = worker.run()
                results[channel] = path
                events.put(("channel_done", channel, path, warning))
            except _Cancelled:
                events.put(("channel_failed", channel, CANCELLED_TEXT))
            except ExportError as exc:
                events.put(("channel_failed", channel, str(exc)))
            except OSError as exc:
                events.put(("channel_failed", channel, f"No se pudo guardar el archivo: {exc}"))
    except Exception as exc:  # cualquier imprevisto: se avisa por cada canal pendiente
        for channel in channels:
            if results[channel] is None:
                events.put(("channel_failed", channel, f"Error inesperado: {exc}"))
    finally:
        events.put(("finished", results))


class _ChannelExport:
    """El archivo de UN canal: baja sus trozos (uno a la vez), los pasa a MPEG-TS, mete los tramos
    negros y lo une todo en el MP4 final."""

    def __init__(self, handle, host, username, password, spec, channel, submit, ffmpeg, stats, chunk_seconds, work_root) -> None:
        self.handle, self.events, self.stop = handle, handle.events, handle.stop
        self.host, self.username, self.password = host, username, password
        self.spec, self.channel, self.submit, self.ffmpeg, self.stats = spec, channel, submit, ffmpeg, stats
        self.pieces = channel_pieces(spec, channel, chunk_seconds)
        self.work_root = work_root or spec.folder
        self.size: tuple[int, int] | None = None
        self.files: dict[int, Path] = {}  # índice de pieza -> su .ts
        self.lost: list[int] = []  # trozos que no se pudieron bajar (se rellenan con negro)
        self._paused = False
        self._last_poll = 0.0

    # -- flujo --------------------------------------------------------------------------------------

    def run(self) -> tuple[str, str | None]:
        if not any(piece.kind == "video" for piece in self.pieces):
            raise ExportError("No hay grabaciones en las horas elegidas")
        total = sum(piece.seconds for piece in self.pieces)
        video = sum(piece.seconds for piece in self.pieces if piece.kind == "video")
        self.events.put(("plan", self.channel, len(self.pieces), total, video, total - video))
        work = self.work_root / f".exportando_CAM{self.channel}_{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            self._download_all(work)
            self._make_gaps(work)
            return self._join(work)
        finally:
            self.events.put(("paused", False))
            shutil.rmtree(work, ignore_errors=True)

    def _request(self, index: int) -> Future:
        piece = self.pieces[index]
        events, channel = self.events, self.channel
        return self.submit(
            self.host, self.username, self.password, channel, piece.start, piece.end, DownloadPriority.BACKGROUND, self.stop,
            progress=lambda received: events.put(("progress", channel, index, received)),
        )

    def _download_all(self, work: Path) -> None:
        video = [i for i, piece in enumerate(self.pieces) if piece.kind == "video"]
        self.events.put(("state", self.channel, "Descargando…", PHASE_DOWNLOADING))
        future: Future | None = self._request(video[0])  # el primero; los demás se piden de a uno, al terminar el anterior
        for position, index in enumerate(video):
            piece = self.pieces[index]
            self.events.put(("piece", self.channel, index, piece.start, piece.end))
            source = self._wait(future)
            attempt = 0
            while source is None and not self.stop.is_set() and attempt < CHUNK_RETRIES:
                self.events.put(("state", self.channel, "Reintentando un trozo…", PHASE_DOWNLOADING))
                if self.stop.wait(CHUNK_RETRY_DELAYS[min(attempt, len(CHUNK_RETRY_DELAYS) - 1)]):
                    break
                attempt += 1
                source = self._wait(self._request(index))
            self._check_stop()
            future = self._request(video[position + 1]) if position + 1 < len(video) else None  # uno solo en vuelo
            if source is None:
                self._lose(index, piece, "no se pudo descargar del DVR")
                continue
            try:
                self._to_ts(index, source, work)
            except ExportError as exc:
                self._lose(index, piece, f"no se pudo convertir ({exc})")
            finally:
                source.unlink(missing_ok=True)
            self.events.put(("piece_done", self.channel, index))
            self.events.put(("state", self.channel, "Descargando…", PHASE_DOWNLOADING))

    def _lose(self, index: int, piece: Piece, reason: str) -> None:
        self.lost.append(index)
        self.events.put(("warning", self.channel, f"El trozo de las {piece.start:%H:%M:%S} {reason}; se rellena con negro."))
        self.events.put(("piece_done", self.channel, index))

    def _to_ts(self, index: int, source: Path, work: Path) -> None:
        if self.size is None:
            self.size = video_size(source)
        target = work / f"p{index:05d}.ts"
        _run_ffmpeg([self.ffmpeg, "-v", "error", "-y", "-i", str(source), "-map", "0:v:0", "-c", "copy", "-f", "mpegts", str(target)], self.stop)
        if not target.exists() or target.stat().st_size == 0:
            raise ExportError("archivo vacío")
        self.files[index] = target

    def _wait(self, future: Future) -> Path | None:
        while True:
            self._poll_live()
            try:
                return future.result(timeout=WAIT_POLL)
            except FutureTimeout:
                if self.stop.is_set():
                    raise _Cancelled()
            except Exception:  # el servicio falló: se trata como una descarga fallida
                return None

    def _poll_live(self) -> None:
        """El embudo pausa solo las descargas mientras hay una vista en vivo (concesión de vivo): aquí
        solo se mira para avisar a la interfaz."""
        now = time.monotonic()
        if now - self._last_poll < STATS_POLL_SECONDS:
            return
        self._last_poll = now
        try:
            info = self.stats()
        except Exception:
            return
        paused = bool(info and info.get("live_holders", 0) > 0)
        if paused != self._paused:
            self._paused = paused
            self.events.put(("paused", paused))

    def _check_stop(self) -> None:
        if self.stop.is_set():
            raise _Cancelled()

    # -- tramos negros y unión ------------------------------------------------------------------------

    def _make_gaps(self, work: Path) -> None:
        wanted = [
            (i, piece) for i, piece in enumerate(self.pieces) if piece.kind == "gap" or i in self.lost
        ]
        if not wanted:
            return
        self.events.put(("state", self.channel, "Preparando los tramos sin grabación…", PHASE_GAPS))
        size = self.size or DEFAULT_SIZE
        font = find_font()
        if font is None:
            self.events.put(("warning", self.channel, "No hay una tipografía instalada: los tramos sin grabación quedan en negro sin texto."))
        for index, piece in wanted:
            self._check_stop()
            target = work / f"p{index:05d}.ts"
            _run_ffmpeg(gap_command(self.ffmpeg, font, target, size, piece.start, piece.seconds), self.stop)
            self.files[index] = target
            self.events.put(("piece_done", self.channel, index))

    def _join(self, work: Path) -> tuple[str, str | None]:
        self.events.put(("state", self.channel, "Uniendo todo en un solo archivo…", PHASE_JOINING))
        listing = work / "lista.txt"
        listing.write_text(
            "".join(f"file '{str(self.files[i]).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for i in sorted(self.files)),
            encoding="utf-8",
        )
        hours = self.spec.cells.get(self.channel, [])
        final = unique_path(self.spec.folder, output_name(self.channel, self.spec.day, hours))
        partial = final.with_name(f".{final.stem}.parcial{final.suffix}")
        try:
            _run_ffmpeg(
                [self.ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0:v:0",
                 "-c", "copy", "-movflags", "+faststart", str(partial)],
                self.stop,
            )
            self.events.put(("state", self.channel, "Verificando…", PHASE_JOINING))
            warning = verify_output(partial, sum(piece.seconds for piece in self.pieces))
            partial.replace(final)
            own_as_user(final)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        notes = []
        gaps = sum(1 for piece in self.pieces if piece.kind == "gap")
        if gaps:
            notes.append(f"{gaps} tramo{'s' if gaps != 1 else ''} sin grabación relleno{'s' if gaps != 1 else ''} con negro")
        if self.lost:
            notes.append(f"{len(self.lost)} trozo{'s' if len(self.lost) != 1 else ''} no se pudo descargar (relleno{'s' if len(self.lost) != 1 else ''} con negro)")
        if warning:
            notes.append(warning)
        return str(final), ("; ".join(notes) if notes else None)
