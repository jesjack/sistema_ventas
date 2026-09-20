from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import cv2

from . import download_client
from .download_manager import DownloadPriority

# Exportar un clip corto (varios segundos o minutos) para conservarlo fuera del
# DVR, que sobrescribe lo antiguo. Sin Qt: la interfaz lanza start_export() y lee
# los avisos de la cola `events` con un temporizador (los hilos NUNCA referencian
# widgets, ver la nota de dvr_info_dialog.py).
#
# Se pide al DVR EXACTAMENTE el rango (una descarga por canal, por el embudo con
# prioridad EXPORT) y se reempaqueta a MP4 sin recodificar con ffmpeg si está
# disponible (0.1 s, sin pérdida; informes/REPRODUCCION_VELOCIDAD.md); si no, se
# deja el .dav original (contenedor dhav, sin cifrar, lo reproducen VLC y otros).
# Antes de dar un archivo por bueno se abre y se comprueba su duración.

ESTIMATED_MBPS_PER_CHANNEL = 2.1  # medido en el DVR real (CBR 2048 kbps + sobrecarga)
SUBFOLDER = "Cámaras"
DOWNLOAD_RETRY_DELAY = 1.0
FFMPEG_TIMEOUT = 300.0
DURATION_TOLERANCE_SECONDS = 1.5
WAIT_POLL = 0.2

# Fases de un canal durante la exportación (cuarto elemento de los avisos "state").
PHASE_QUEUED = "queued"  # esperando turno en el embudo del DVR
PHASE_DOWNLOADING = "downloading"  # llegan bytes del DVR (aviso "progress")
PHASE_RETRYING = "retrying"
PHASE_CONVERTING = "converting"  # remux a MP4 (o mover el .dav)
PHASE_VERIFYING = "verifying"
CANCELLED_TEXT = "Cancelado"


class ExportError(Exception):
    pass


def user_home() -> Path:
    """Carpeta personal del usuario REAL. No se fía de $HOME: cuando la app la lanza el
    POS (que corre como root por sudo), el proceso baja a tu usuario pero hereda
    HOME=/root, y `Path.home()` devolvía /root. Se lee del registro de usuarios
    (passwd) por el uid efectivo, o por SUDO_USER si de verdad se corre como root."""
    if os.name == "posix":
        try:
            import pwd

            uid = os.geteuid()
            sudo_user = os.environ.get("SUDO_USER")
            entry = pwd.getpwnam(sudo_user) if uid == 0 and sudo_user else pwd.getpwuid(uid)
            return Path(entry.pw_dir)
        except (KeyError, ImportError, OSError):
            pass
    return Path.home()


def videos_folder(home: Path) -> Path:
    """La carpeta de vídeos de ese usuario: la que declara XDG (`user-dirs.dirs`, que en un
    sistema en español es "Vídeos", con tilde), o la que exista, o "Videos"."""
    config = home / ".config" / "user-dirs.dirs"
    try:
        match = re.search(r'^XDG_VIDEOS_DIR="([^"]+)"', config.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        match = None
    if match:
        declared = Path(match.group(1).replace("$HOME", str(home)))
        if declared.is_absolute() and declared != home:
            return declared
    for name in ("Vídeos", "Videos"):
        if (home / name).is_dir():
            return home / name
    return home / "Videos"


def default_export_folder() -> Path:
    return videos_folder(user_home()) / SUBFOLDER


def _invoking_ids() -> tuple[int, int] | None:
    """(uid, gid) del usuario real si este proceso corre como root por sudo (los archivos
    guardados deben ser de ese usuario, no de root)."""
    if os.name != "posix" or os.geteuid() != 0:
        return None
    try:
        return int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
    except (KeyError, ValueError):
        return None


def parse_folder(text: str) -> Path | None:
    """La carpeta que describe el texto escrito por el usuario, o None si no sirve: vacío, ruta
    relativa, o que pasa por algo que no es una carpeta. Puede no existir aún (`make_folder`
    la crea) mientras la primera carpeta existente hacia arriba sea, de hecho, una carpeta.
    "~" es la carpeta personal del usuario real (ver `user_home`)."""
    text = text.strip()
    if not text:
        return None
    if text == "~" or text.startswith("~/"):
        text = str(user_home() / text[2:])
    path = Path(text)
    if not path.is_absolute():
        return None
    probe = path
    while not probe.exists():
        if probe == probe.parent:
            return None
        probe = probe.parent
    return path if probe.is_dir() else None


def make_folder(folder: Path) -> None:
    """Crea la carpeta (y las que falten arriba); las nuevas quedan a nombre del usuario real."""
    missing = []
    probe = folder
    while not probe.exists() and probe != probe.parent:
        missing.append(probe)
        probe = probe.parent
    folder.mkdir(parents=True, exist_ok=True)
    ids = _invoking_ids()
    if ids:
        for created in reversed(missing):  # de la de arriba a la de abajo
            try:
                os.chown(created, *ids)
            except OSError:
                pass


def own_as_user(path: Path) -> None:
    ids = _invoking_ids()
    if ids:
        try:
            os.chown(path, *ids)
        except OSError:
            pass


@dataclass(frozen=True)
class ClipRange:
    start: datetime
    end: datetime

    @property
    def duration(self) -> float:
        return (self.end - self.start).total_seconds()

    @classmethod
    def around(
        cls,
        moment: datetime,
        before: float,
        after: float,
        earliest: datetime | None = None,
        latest: datetime | None = None,
    ) -> "ClipRange":
        """[moment - before, moment + after], recortado a lo que hay grabado."""
        start, end = moment - timedelta(seconds=before), moment + timedelta(seconds=after)
        if earliest is not None:
            start = max(start, earliest)
        if latest is not None:
            end = min(end, latest)
        return cls(start, end)


def clip_filename(channel: int, clip_range: ClipRange, extension: str) -> str:
    return (
        f"CAM{channel}_{clip_range.start:%Y-%m-%d_%H-%M-%S}_a_{clip_range.end:%H-%M-%S}{extension}"
    )


def unique_path(folder: Path, filename: str) -> Path:
    """`folder/filename`, o con " (2)", " (3)"... si ya existe (nunca se pisa un archivo)."""
    candidate = folder / filename
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def estimate_bytes(clip_range: ClipRange, channel_count: int) -> float:
    return clip_range.duration * ESTIMATED_MBPS_PER_CHANNEL * 1e6 / 8 * channel_count


def format_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def remux_to_mp4(source: Path, destination: Path, ffmpeg: str) -> None:
    """Copia el video a un MP4 sin recodificar (rápido y sin pérdida)."""
    command = [
        ffmpeg, "-y", "-v", "error", "-i", str(source),
        "-c", "copy", "-map", "0:v:0", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
        str(destination),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExportError(f"No se pudo convertir el video: {exc}") from exc
    if result.returncode != 0 or not destination.exists() or destination.stat().st_size == 0:
        raise ExportError(f"No se pudo convertir el video: {result.stderr.strip()[-200:] or 'ffmpeg falló'}")


def verify_clip(path: Path, expected_seconds: float) -> str | None:
    """Abre el archivo y comprueba que tenga video. Devuelve un AVISO (texto) si su
    duración no coincide con lo pedido (p. ej. faltan grabaciones en ese tramo);
    lanza ExportError si no se puede abrir o no tiene imagen."""
    if not path.exists() or path.stat().st_size == 0:
        raise ExportError("El archivo quedó vacío")
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        if not capture.isOpened():
            raise ExportError("El archivo guardado no se puede abrir")
        ok, _ = capture.read()
        if not ok:
            raise ExportError("El archivo guardado no tiene imagen")
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = capture.get(cv2.CAP_PROP_FPS)
    finally:
        capture.release()
    if frames and fps and frames > 0 and fps > 0:
        duration = frames / fps
        if abs(duration - expected_seconds) > max(DURATION_TOLERANCE_SECONDS, expected_seconds * 0.05):
            return f"dura {duration:.0f} s de los {expected_seconds:.0f} s pedidos"
    return None


class ClipExport:
    """Exportación en curso: `events` (cola) y `cancel()`.

    Avisos en `events`, siempre tuplas:
      ("state", canal, texto[, fase])    progreso de un canal (fase: PHASE_*, o ausente si no cambia)
      ("progress", canal, bytes)         bytes recibidos del DVR hasta ahora (0 = ya arrancó)
      ("done", canal, ruta, aviso|None)  ese canal quedó guardado
      ("failed", canal, mensaje)         ese canal no se pudo
      ("finished", {canal: ruta|None})   terminó todo (nunca falta este aviso)"""

    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def cancel(self) -> None:
        self.stop.set()

    def finished(self) -> bool:
        return self.thread is not None and not self.thread.is_alive()


def start_export(
    host: str,
    username: str,
    password: str,
    channels: list[int],
    clip_range: ClipRange,
    folder: Path,
    submit: Callable[..., Future] | None = None,
    ffmpeg: str | None | bool = True,
) -> ClipExport:
    """Lanza la exportación en un hilo aparte. `ffmpeg=True` busca el del sistema; None = no usar (queda .dav)."""
    handle = ClipExport()
    ffmpeg_path = find_ffmpeg() if ffmpeg is True else (ffmpeg or None)
    handle.thread = threading.Thread(
        target=_run_export,
        args=(handle, host, username, password, list(channels), clip_range, Path(folder), submit or download_client.submit, ffmpeg_path),
        name="ClipExport",
        daemon=True,
    )
    handle.thread.start()
    return handle


def _run_export(
    handle: ClipExport,
    host: str,
    username: str,
    password: str,
    channels: list[int],
    clip_range: ClipRange,
    folder: Path,
    submit: Callable[..., Future],
    ffmpeg: str | None,
) -> None:
    results: dict[int, str | None] = {channel: None for channel in channels}
    events = handle.events

    def request(channel: int) -> Future:
        return submit(
            host, username, password, channel, clip_range.start, clip_range.end, DownloadPriority.EXPORT, handle.stop,
            progress=lambda received: events.put(("progress", channel, received)),
        )

    def wait(future: Future) -> Path | None:
        while True:
            try:
                return future.result(timeout=WAIT_POLL)
            except FutureTimeout:
                if handle.stop.is_set():
                    return None
            except Exception:  # el servicio falló: se trata como una descarga fallida
                return None

    try:
        make_folder(folder)
        # Se piden todos de una vez: el embudo los sirve de a dos, por prioridad.
        futures = {channel: request(channel) for channel in channels}
        for channel in channels:
            events.put(("state", channel, "En cola…", PHASE_QUEUED))
        for channel in channels:
            if handle.stop.is_set():
                events.put(("failed", channel, CANCELLED_TEXT))
                continue
            events.put(("state", channel, "Descargando…"))
            source = wait(futures[channel])
            if source is None and not handle.stop.is_set():
                events.put(("state", channel, "Reintentando la descarga…", PHASE_RETRYING))
                time.sleep(DOWNLOAD_RETRY_DELAY)
                source = wait(request(channel))
            if source is None:
                events.put(("failed", channel, CANCELLED_TEXT if handle.stop.is_set() else "No se pudo descargar del DVR"))
                continue
            try:
                events.put(("state", channel, "Convirtiendo…" if ffmpeg else "Guardando…", PHASE_CONVERTING))
                extension = ".mp4" if ffmpeg else ".dav"
                final = unique_path(folder, clip_filename(channel, clip_range, extension))
                partial = final.with_name(f"{final.stem}.part{extension}")
                try:
                    if ffmpeg:
                        remux_to_mp4(source, partial, ffmpeg)
                    else:
                        shutil.move(str(source), str(partial))
                    events.put(("state", channel, "Verificando…", PHASE_VERIFYING))
                    warning = verify_clip(partial, clip_range.duration)
                    partial.replace(final)
                    own_as_user(final)
                except BaseException:
                    partial.unlink(missing_ok=True)
                    raise
                results[channel] = str(final)
                events.put(("done", channel, str(final), warning))
            except ExportError as exc:
                events.put(("failed", channel, str(exc)))
            except OSError as exc:
                events.put(("failed", channel, f"No se pudo guardar el archivo: {exc}"))
            finally:
                source.unlink(missing_ok=True)
    except Exception as exc:  # cualquier imprevisto: se avisa por cada canal pendiente
        for channel in channels:
            if results[channel] is None:
                events.put(("failed", channel, f"Error inesperado: {exc}"))
    finally:
        events.put(("finished", results))
