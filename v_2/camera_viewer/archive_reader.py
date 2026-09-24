from __future__ import annotations

import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import archive_index as idx

# find_ffmpeg se reimplementa aquí (no se importa de export_clip.py) a propósito: este módulo lo
# usa download_manager.py, y export_clip.py importa de download_manager -- importar de ahí
# formaría un ciclo (download_manager -> archive_reader -> export_clip -> download_manager).


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")

# Leer del archivo local (archiver.py) en vez de pedirle al DVR: lo que hace que reproducir,
# guardar un clip o exportar horas de un día que el DVR ya no tiene funcione igual, y que un día
# que SÍ tiene deje de pedirle al DVR lo que ya está en la PC ("no haría falta solicitarlas al
# dvr sino a la memoria", como pidió el usuario). Sin Qt, lo usa RecordingDownloadManager.submit()
# (download_manager.py) antes de encolar cualquier descarga real.
#
# V1: solo se sirve del archivo cuando el rango pedido cae ENTERO dentro de UN solo segmento
# archivado (ver find_covering_segment) -- el caso común, ya que los trozos del archivador (5
# min) suelen ser más grandes que un bloque de reproducción o una pieza de exportar horas. Si el
# rango cae a caballo entre dos segmentos, se pide al DVR como siempre: unir varios segmentos es
# una mejora futura, no algo que haga falta para que esto ya sea útil.
#
# El recorte es con `-c copy` (sin recodificar: rápido, no usa CPU/GPU de más) -- puede empezar
# un poco antes de lo pedido (el cuadro clave más cercano hacia atrás dentro del segmento), igual
# que ya puede pasar con un bloque bajado del DVR; quien reproduce ya sabe avanzar al punto exacto
# dentro de lo que carga (ver channel_player.py), así que esto no es una regresión de precisión.

EXTRACT_TIMEOUT = 60.0


def find_covering_segment(segments: list[idx.Segment], start: datetime, end: datetime) -> idx.Segment | None:
    """El primer segmento (de los que se cruzan con [start, end)) que lo cubre COMPLETO, o None
    si ninguno lo hace (incluido el caso de que el rango esté repartido entre varios)."""
    for segment in segments:
        if segment.start <= start and end <= segment.end:
            return segment
    return None


def lookup(archive_dir: Path, channel: int, start: datetime, end: datetime) -> idx.Segment | None:
    """¿[start, end) del canal `channel` ya está completo en un solo segmento archivado? Abre y
    cierra su propia conexión -- una consulta rápida y bastante infrecuente frente a una
    descarga real como para no valer la pena mantener una compartida. None también si el
    archivo ni siquiera existe todavía (lo normal: la mayoría de los sistemas no tendrán uno)."""
    index_path = archive_dir / "index.sqlite3"
    if not index_path.exists():
        return None
    conn = idx.open_db(index_path)
    try:
        segments = idx.segments_covering(conn, channel, start, end)
    finally:
        conn.close()
    return find_covering_segment(segments, start, end)


def extract_command(ffmpeg: str, source: Path, offset_seconds: float, duration_seconds: float, destination: Path) -> list[str]:
    return [
        ffmpeg, "-v", "error", "-y",
        "-ss", f"{max(0.0, offset_seconds):.3f}", "-i", str(source), "-t", f"{max(0.0, duration_seconds):.3f}",
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        str(destination),
    ]


def extract(
    archive_dir: Path,
    segment: idx.Segment,
    start: datetime,
    end: datetime,
    destination_dir: Path,
    stop_event: threading.Event | None = None,
    ffmpeg: str | None = None,
) -> Path | None:
    """Recorta [start, end) de `segment` (ya se sabe que lo cubre entero, ver lookup) a un
    archivo NUEVO en `destination_dir`. None si algo falla (fuera de la vista: falta ffmpeg, el
    archivo de origen ya no existe, se canceló) -- el llamador entonces sigue como si esto nunca
    se hubiera intentado y pide el rango al DVR."""
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return None
    source = archive_dir / segment.path
    if not source.exists():
        return None
    if stop_event is not None and stop_event.is_set():
        return None

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"ch{segment.channel}_{uuid.uuid4().hex}.mp4"
    offset = (start - segment.start).total_seconds()
    duration = (end - start).total_seconds()
    command = extract_command(ffmpeg, source, offset, duration, destination)
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    try:
        returncode = process.wait(timeout=EXTRACT_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        destination.unlink(missing_ok=True)
        return None

    if (stop_event is not None and stop_event.is_set()) or returncode != 0 or not destination.exists() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        return None
    return destination
