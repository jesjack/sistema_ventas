from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .export_clip import ExportError, find_ffmpeg, own_as_user
from .export_hours import media_duration, verify_output

# Recomprime un segmento crudo (aterrizado tal cual del DVR, ver archiver.py) a MP4 H.264 con
# calidad constante, para que el archivo local ocupe una fracción de lo que ocupa en el DVR
# (medido el 2026-09-21/23: 3-30x según cuánto se mueve la escena -- el DVR graba a bitrate FIJO,
# gaste o no gaste esa velocidad en algo que realmente cambió). Por GPU (VAAPI, la que trae la
# PC) cuando está disponible -- unos 3-4 s por minuto de video, una fracción de núcleo -- y por
# CPU (libx264) si no. Nunca toca el archivo original hasta tener el nuevo, verificado, listo.
#
# Un fotograma clave cada KEYFRAME_SECONDS (por tiempo, no por cantidad de cuadros: los canales
# no siempre van a los mismos fps) para poder recortar sin recodificar en cualquier segmento de
# ~4 s en vez de solo al principio del archivo -- el costo es un archivo algo más grande; el
# beneficio es que abrir/recortar el archivo compactado (reproducir, exportar un clip) solo tiene
# que decodificar de más un puñado de cuadros, no el video entero.

VAAPI_DEVICE_CANDIDATES = ("/dev/dri/renderD128", "/dev/dri/renderD129", "/dev/dri/card0")

# Calidad constante (qp, "quantization parameter": mas bajo = mejor calidad y mas peso). Elegido
# de una muestra real de los 4 canales a 3 horas del dia (incluida la madrugada): a qp30 el
# archivo queda en ~10% del original (9.9x menos) con una perdida que no se nota comparando
# recortes lado a lado; qp34 ahorra mas (17x) pero ya se ve algo mas suave en texturas finas
# (piso, ropa); qp26 casi no pierde nada pero ahorra menos (5x). qp30 es el default razonable.
QUALITY_LOW = 34  # maximo ahorro
QUALITY_MEDIUM = 30  # default
QUALITY_HIGH = 26  # minima perdida
KEYFRAME_SECONDS = 4.0
FFMPEG_TIMEOUT = 600.0  # un segmento de 5 min nunca deberia tardar tanto; corte de seguridad

_AUTO_DEVICE = object()  # distingue "no me dijeron nada, detecta tú" de "vaapi_device=None: sin GPU a propósito"


class CompactionError(ExportError):
    pass


@dataclass(frozen=True)
class CompactionResult:
    path: Path
    bytes: int
    used_gpu: bool


def find_vaapi_device(candidates: tuple[str, ...] = VAAPI_DEVICE_CANDIDATES) -> str | None:
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _keyframe_filter() -> str:
    # Cuadro clave cada KEYFRAME_SECONDS de tiempo de PRESENTACION (no cada N cuadros): asi el
    # intervalo es el mismo sin importar los fps de cada canal.
    return f"expr:gte(t,n_forced*{KEYFRAME_SECONDS:g})"


def gpu_command(ffmpeg: str, device: str, source: Path, destination: Path, qp: int) -> list[str]:
    return [
        ffmpeg, "-v", "error", "-y",
        "-hwaccel", "vaapi", "-hwaccel_device", device, "-hwaccel_output_format", "vaapi",
        "-i", str(source), "-map", "0:v:0",
        "-c:v", "h264_vaapi", "-qp", str(qp), "-force_key_frames", _keyframe_filter(),
        "-movflags", "+faststart", str(destination),
    ]


def cpu_command(ffmpeg: str, source: Path, destination: Path, qp: int) -> list[str]:
    return [
        ffmpeg, "-v", "error", "-y", "-i", str(source), "-map", "0:v:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(qp), "-force_key_frames", _keyframe_filter(),
        "-movflags", "+faststart", str(destination),
    ]


def _run(command: list[str], stop: threading.Event | None, timeout: float) -> None:
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        raise CompactionError(f"No se pudo ejecutar ffmpeg: {exc}") from exc
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if stop is not None and stop.wait(0.2):
                process.kill()
                process.wait()
                raise CompactionError("Cancelado")
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise CompactionError("ffmpeg tardó demasiado compactando")
        stderr = process.stderr.read() if process.stderr else ""
    finally:
        if process.stderr:
            process.stderr.close()
    if process.returncode != 0:
        raise CompactionError(f"ffmpeg falló: {stderr.strip()[-200:] or process.returncode}")


def compact(
    source: Path,
    destination: Path,
    duration_seconds: float,
    quality: int = QUALITY_MEDIUM,
    ffmpeg: str | None = None,
    vaapi_device: str | None | object = _AUTO_DEVICE,
    stop: threading.Event | None = None,
) -> CompactionResult:
    """Recomprime `source` (el .dav crudo) a `destination` (un .mp4 nuevo). Prueba la GPU primero
    (si hay un dispositivo VAAPI) y cae a CPU si la GPU falla o no está -- algunos equipos no
    tienen el perfil H.264 habilitado por VAAPI aunque el dispositivo exista (visto en la propia
    PC de pruebas con HEVC). `destination` NUNCA queda a medias: se escribe aparte y solo se dice
    lista si abre y su duración es la esperada.

    `vaapi_device`: sin dar nada, se detecta solo (`find_vaapi_device`); un `str` fuerza ESE
    dispositivo; `None` fuerza CPU (para pruebas, o si se sabe que la GPU no sirve)."""
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise CompactionError("Hace falta ffmpeg para compactar")
    partial = destination.with_name(f".{destination.stem}.parcial{destination.suffix}")
    device = find_vaapi_device() if vaapi_device is _AUTO_DEVICE else vaapi_device
    used_gpu = False
    try:
        if device is not None:
            try:
                _run(gpu_command(ffmpeg, device, source, partial, quality), stop, FFMPEG_TIMEOUT)
                used_gpu = True
            except CompactionError:
                partial.unlink(missing_ok=True)
                if stop is not None and stop.is_set():
                    raise
                used_gpu = False  # la GPU falló (perfil no soportado, driver...): se sigue por CPU
        if not used_gpu:
            _run(cpu_command(ffmpeg, source, partial, quality), stop, FFMPEG_TIMEOUT)
        warning = verify_output(partial, duration_seconds)
        if warning:  # la duración no cuadra: algo salió mal al recomprimir, no algo del origen
            raise CompactionError(f"la copia comprimida {warning}")
        size = partial.stat().st_size
        partial.replace(destination)
        own_as_user(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return CompactionResult(destination, size, used_gpu)
