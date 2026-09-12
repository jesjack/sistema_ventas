"""Herramienta de diagnostico standalone para encontrar el limite real de
concurrencia/persistencia que aguanta el DVR Dahua XVR51xxHS-S2 antes de
dejar de responder (ver camera_viewer/DVR_HARDWARE.md para el contexto
completo del problema que motivo esto).

Deliberadamente NO depende de camera_viewer/dvr_client.py: la idea es medir
el comportamiento del DVR "en crudo", sin la logica de reconexion/backoff/
serializacion que ya le pusimos a la app, para no mezclar variables.

Metodologia: escala la carga de a un escalon a la vez (1, 2, 3, 4 conexiones
simultaneas), y ANTES y DESPUES de cada escalon hace un chequeo de salud
liviano (una sola peticion HTTP CGI, sin reintentos) para detectar el
momento exacto en que el DVR deja de responder. En cuanto un chequeo de
salud falla, el script se detiene de inmediato (no sigue escalando ni
reintenta) y lo reporta claramente -- en ese punto el DVR necesita un
reinicio manual antes de continuar con el siguiente escalon.

Uso:
    .venv/bin/python cameras/dvr_stress_test.py --phase live-concurrency
    .venv/bin/python cameras/dvr_stress_test.py --phase rec-concurrency
    .venv/bin/python cameras/dvr_stress_test.py --phase live-persistence --duration 300
    .venv/bin/python cameras/dvr_stress_test.py --phase rec-persistence --duration 300
    .venv/bin/python cameras/dvr_stress_test.py --phase live-concurrency --levels 3,4   # reanudar

Cada fase se detiene sola en el primer fallo de salud; para reanudar tras
reiniciar el DVR, vuelve a invocar con --levels empezando en el escalon
que fallo (o el siguiente, si quieres reconfirmar el que fallo).
"""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import requests
from requests.auth import HTTPDigestAuth

HOST = "192.168.1.108"
USERNAME = "nancy"
PASSWORD = "miriam.2017"
RTSP_PORT = 554
LIVE_SUBTYPE = 1
CHANNELS = (1, 2, 3, 4)

HEALTH_CHECK_TIMEOUT = 8.0
COOLDOWN_BETWEEN_LEVELS = 8.0

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs" / "dvr_stress_test"

_log_file = None


def _log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    if _log_file is not None:
        _log_file.write(line + "\n")
        _log_file.flush()


def _open_log_file() -> None:
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
    _log_file = path.open("a", encoding="utf-8")
    _log("Log de esta corrida: %s" % path)


# -- salud del DVR (chequeo liviano, sin reintentos) -----------------------


@dataclass
class HealthResult:
    ok: bool
    elapsed: float
    detail: str


def health_check(timeout: float = HEALTH_CHECK_TIMEOUT) -> HealthResult:
    t0 = time.monotonic()
    try:
        r = requests.get(
            f"http://{HOST}/cgi-bin/magicBox.cgi?action=getSystemInfo",
            auth=HTTPDigestAuth(USERNAME, PASSWORD),
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        if r.status_code == 200 and "serialNumber" in r.text:
            return HealthResult(True, elapsed, r.text.strip().replace("\n", " | "))
        return HealthResult(False, elapsed, f"HTTP {r.status_code}: {r.text[:200]!r}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return HealthResult(False, elapsed, f"{type(exc).__name__}: {exc}")


class BreakpointFound(Exception):
    def __init__(self, phase: str, level, health: HealthResult):
        self.phase = phase
        self.level = level
        self.health = health
        super().__init__(f"{phase} nivel={level}: {health.detail}")


def _require_healthy(phase: str, level, when: str) -> HealthResult:
    result = health_check()
    status = "OK" if result.ok else "*** SIN RESPUESTA ***"
    _log(f"  chequeo de salud ({when}): {status} en {result.elapsed:.2f}s -- {result.detail}")
    if not result.ok:
        raise BreakpointFound(phase, level, result)
    return result


# -- medicion de red (bytes reales por la interfaz, no estimados) ---------


def _detect_iface(host: str) -> str | None:
    try:
        out = subprocess.check_output(["ip", "route", "get", host], text=True, timeout=5)
        match = re.search(r"\bdev\s+(\S+)", out)
        return match.group(1) if match else None
    except Exception as exc:
        _log(f"  no se pudo detectar la interfaz de red ({exc}); Mbps no disponible")
        return None


_IFACE = _detect_iface(HOST)


def _read_iface_bytes(iface: str) -> tuple[int, int] | None:
    try:
        with open("/proc/net/dev", "r", encoding="ascii") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                if name.strip() != iface:
                    continue
                fields = rest.split()
                rx_bytes = int(fields[0])
                tx_bytes = int(fields[8])
                return rx_bytes, tx_bytes
    except Exception:
        pass
    return None


class NetworkMeter:
    """Mide bytes reales RX+TX de la interfaz durante una ventana, para
    reportar Mbps real en vez de estimarlo por tamano de frame decodificado."""

    def __init__(self) -> None:
        self._iface = _IFACE
        self._start = None
        self._t0 = None

    def __enter__(self) -> "NetworkMeter":
        self._t0 = time.monotonic()
        self._start = _read_iface_bytes(self._iface) if self._iface else None
        return self

    def __exit__(self, *exc) -> None:
        pass

    def mbps(self) -> float | None:
        if self._iface is None or self._start is None:
            return None
        end = _read_iface_bytes(self._iface)
        if end is None:
            return None
        elapsed = max(time.monotonic() - self._t0, 1e-6)
        total_bytes = (end[0] - self._start[0]) + (end[1] - self._start[1])
        return (total_bytes * 8) / elapsed / 1_000_000


# -- resultados por canal ---------------------------------------------------


@dataclass
class ChannelResult:
    channel: int
    opened: bool = False
    open_latency: float = 0.0
    time_to_first_frame: float | None = None
    frames_read: int = 0
    resolution: tuple[int, int] | None = None
    measured_fps: float = 0.0
    error: str = ""


def _measure_stream(url: str, channel: int, duration: float, result: ChannelResult, paced: bool = False) -> None:
    """paced=True reproduce a la velocidad real del clip (igual que
    DVRClient._play_single_clip en camera_viewer/dvr_client.py: pausa cada
    frame segun 1/fps) en vez de leer tan rapido como el DVR entregue datos.
    Solo tiene sentido para grabaciones -- en vivo el RTSP ya entrega a
    ritmo real por si solo, no hay nada que pausar."""
    t0 = time.monotonic()
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    result.open_latency = time.monotonic() - t0
    result.opened = capture.isOpened()
    if not result.opened:
        result.error = "no se pudo abrir"
        capture.release()
        return

    fps = 25.0
    frame_interval = 0.0
    if paced:
        reported_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if reported_fps > 0 and reported_fps < float("inf"):
            fps = reported_fps
        frame_interval = 1.0 / fps

    deadline = time.monotonic() + duration
    first_frame_t0 = time.monotonic()
    next_frame_at = first_frame_t0
    try:
        while time.monotonic() < deadline:
            if paced:
                now = time.monotonic()
                if now < next_frame_at:
                    time.sleep(next_frame_at - now)

            ok, frame = capture.read()
            if not ok:
                if result.frames_read == 0:
                    result.error = "abrio pero no entrego ningun frame"
                break
            if result.frames_read == 0:
                result.time_to_first_frame = time.monotonic() - first_frame_t0
                h, w = frame.shape[:2]
                result.resolution = (w, h)
            result.frames_read += 1

            if paced:
                next_frame_at = max(next_frame_at + frame_interval, time.monotonic())
    finally:
        capture.release()

    elapsed = time.monotonic() - first_frame_t0
    if elapsed > 0:
        result.measured_fps = result.frames_read / elapsed


def _live_url(channel: int) -> str:
    return (
        f"rtsp://{USERNAME}:{PASSWORD}@{HOST}:{RTSP_PORT}"
        f"/cam/realmonitor?channel={channel}&subtype={LIVE_SUBTYPE}"
    )


# -- grabaciones: encontrar un clip real y armar su URL --------------------


def _parse_items(payload: str) -> dict[int, dict[str, str]]:
    items: dict[int, dict[str, str]] = {}
    pattern = re.compile(r"items\[(\d+)\]\.([A-Za-z0-9_]+)=(.*)")
    for line in payload.splitlines():
        match = pattern.match(line.strip())
        if match:
            items.setdefault(int(match.group(1)), {})[match.group(2)] = match.group(3).strip()
    return items


def find_existing_clip(channel: int, lookback_hours: int = 72) -> tuple[datetime, datetime] | None:
    """Busca grabaciones reales de este canal en las ultimas `lookback_hours`
    horas y devuelve (start, end) del clip mas reciente que encuentre."""
    auth = HTTPDigestAuth(USERNAME, PASSWORD)
    base = f"http://{HOST}/cgi-bin/mediaFileFind.cgi"
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=lookback_hours)

    response = requests.get(f"{base}?action=factory.create", auth=auth, timeout=15)
    match = re.search(r"result=(\d+)", response.text)
    if not match:
        return None
    object_id = match.group(1).strip()

    try:
        start_q = start_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
        end_q = end_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
        requests.get(
            f"{base}?action=findFile&object={object_id}&condition.Channel={channel}"
            f"&condition.StartTime={start_q}&condition.EndTime={end_q}",
            auth=auth,
            timeout=15,
        )
        results = requests.get(f"{base}?action=findNextFile&object={object_id}&count=200", auth=auth, timeout=15)
        clips = []
        for item in _parse_items(results.text).values():
            s, e = item.get("StartTime"), item.get("EndTime")
            if s and e:
                clips.append(
                    (
                        datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S"),
                        datetime.strptime(e.strip(), "%Y-%m-%d %H:%M:%S"),
                    )
                )
        if not clips:
            return None
        return max(clips, key=lambda c: c[1])  # el mas reciente
    finally:
        try:
            requests.get(f"{base}?action=destroy&object={object_id}", auth=auth, timeout=10)
        except Exception:
            pass


def _recording_url(channel: int, start: datetime, end: datetime) -> str:
    start_q = start.strftime("%Y-%m-%d%%20%H:%M:%S")
    end_q = end.strftime("%Y-%m-%d%%20%H:%M:%S")
    return (
        f"http://{USERNAME}:{PASSWORD}@{HOST}/cgi-bin/loadfile.cgi"
        f"?action=startLoad&channel={channel}&startTime={start_q}&endTime={end_q}"
    )


# -- fase 1: concurrencia escalonada ---------------------------------------


def run_concurrency_level(phase: str, mode: str, level: int, duration: float, paced: bool = False) -> list[ChannelResult]:
    channels = CHANNELS[:level]
    ritmo = "a ritmo real (como la app)" if paced and mode == "rec" else "sin freno (maxima velocidad)" if mode == "rec" else "vivo"
    _log(f"--- {mode}: {level} conexion(es) simultanea(s), canales {channels}, {duration:.0f}s c/u, {ritmo} ---")

    if mode == "rec":
        clip_by_channel: dict[int, tuple[datetime, datetime]] = {}
        for ch in channels:
            clip = find_existing_clip(ch)
            if clip is None:
                _log(f"  canal {ch}: no se encontraron grabaciones existentes en las ultimas 72h -- se omite")
            else:
                clip_by_channel[ch] = clip
        channels = tuple(clip_by_channel.keys())
        if not channels:
            _log("  ningun canal tiene grabaciones disponibles para probar en este nivel; se omite el nivel")
            return []

    results = [ChannelResult(channel=ch) for ch in channels]
    threads = []
    with NetworkMeter() as meter:
        t_start = time.monotonic()
        for ch, result in zip(channels, results):
            if mode == "live":
                url = _live_url(ch)
            else:
                clip_start, clip_end = clip_by_channel[ch]
                # Punto aleatorio dentro del clip real, dejando margen para
                # que queden al menos `duration` segundos de video por leer.
                usable = max((clip_end - clip_start).total_seconds() - duration, 0)
                offset = random.uniform(0, usable) if usable > 0 else 0
                play_start = clip_start + timedelta(seconds=offset)
                url = _recording_url(ch, play_start, clip_end)
            thread = threading.Thread(target=_measure_stream, args=(url, ch, duration, result, paced and mode == "rec"))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join(timeout=duration + 35)  # +35: margen sobre el timeout interno de ffmpeg (~30s)
        total_elapsed = time.monotonic() - t_start
        mbps = meter.mbps()

    for r in results:
        if r.opened:
            res_txt = f"{r.resolution[0]}x{r.resolution[1]}" if r.resolution else "?"
            _log(
                f"  canal {r.channel}: abrio en {r.open_latency:.2f}s, primer frame en "
                f"{(r.time_to_first_frame or 0):.2f}s, {r.frames_read} frames en la ventana "
                f"(~{r.measured_fps:.1f} fps), resolucion {res_txt}"
            )
        else:
            _log(f"  canal {r.channel}: FALLO ({r.error}) tras {r.open_latency:.2f}s")

    _log(
        f"  nivel completo en {total_elapsed:.1f}s total"
        + (f", ~{mbps:.2f} Mbps agregados (RX+TX interfaz)" if mbps is not None else "")
    )
    return results


def run_concurrency_phase(mode: str, levels: list[int], duration: float, paced: bool = False) -> None:
    phase = f"{mode}-concurrency"
    _log(f"=== Fase: concurrencia escalonada ({mode}) -- niveles {levels}{' (a ritmo real)' if paced else ''} ===")
    _require_healthy(phase, "inicio", "antes de empezar")

    for level in levels:
        run_concurrency_level(phase, mode, level, duration, paced=paced)
        _require_healthy(phase, level, "despues de este nivel")
        if level != levels[-1]:
            _log(f"  enfriamiento de {COOLDOWN_BETWEEN_LEVELS:.0f}s antes del siguiente nivel...")
            time.sleep(COOLDOWN_BETWEEN_LEVELS)

    _log(f"=== Fase {phase} completa: ningun nivel hizo fallar al DVR ===")


# -- fase 2: persistencia (una sola conexion, sostenida) -------------------


def run_persistence_phase(mode: str, channel: int, duration: float, sample_interval: float) -> None:
    phase = f"{mode}-persistence"
    _log(f"=== Fase: persistencia ({mode}), canal {channel}, {duration:.0f}s, muestreo cada {sample_interval:.0f}s ===")
    _require_healthy(phase, "inicio", "antes de empezar")

    if mode == "live":
        url = _live_url(channel)
    else:
        clip = find_existing_clip(channel)
        if clip is None:
            _log(f"  canal {channel}: no hay grabaciones disponibles; fase omitida")
            return
        clip_start, clip_end = clip
        url = _recording_url(channel, clip_start, clip_end)
        available = (clip_end - clip_start).total_seconds()
        if available < duration:
            _log(f"  aviso: el clip encontrado solo tiene {available:.0f}s (menos que los {duration:.0f}s pedidos)")

    t0 = time.monotonic()
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    open_latency = time.monotonic() - t0
    if not capture.isOpened():
        _log(f"  no se pudo abrir la conexion (tras {open_latency:.2f}s) -- fase abortada")
        capture.release()
        return
    _log(f"  conexion abierta en {open_latency:.2f}s")

    frames_total = 0
    next_sample = time.monotonic() + sample_interval
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            ok, _frame = capture.read()
            if not ok:
                _log(f"  la lectura se corto sola a los {time.monotonic() - t0:.0f}s ({frames_total} frames leidos)")
                break
            frames_total += 1

            if time.monotonic() >= next_sample:
                elapsed = time.monotonic() - t0
                fps_so_far = frames_total / elapsed if elapsed > 0 else 0
                _log(f"  [t={elapsed:6.0f}s] {frames_total} frames leidos (~{fps_so_far:.1f} fps)")
                health = health_check()
                status = "OK" if health.ok else "*** SIN RESPUESTA ***"
                _log(f"           chequeo de salud paralelo: {status} en {health.elapsed:.2f}s -- {health.detail}")
                if not health.ok:
                    capture.release()
                    raise BreakpointFound(phase, f"persistencia t={elapsed:.0f}s", health)
                next_sample = time.monotonic() + sample_interval
    finally:
        capture.release()

    _require_healthy(phase, "fin", "al terminar la fase")
    _log(f"=== Fase {phase} completa: {frames_total} frames leidos, el DVR siguio respondiendo ===")


# -- fase 3: ciclos repetidos (nunca mas de `pair_size` a la vez, pero uno --
# tras otro sin parar) -- para distinguir un limite de PICO de concurrencia
# de un limite ACUMULADO en el tiempo, sin importar el pico. -------------


def _channel_groups(size: int) -> list[tuple[int, ...]]:
    return [CHANNELS[i : i + size] for i in range(0, len(CHANNELS), size)]


def run_cyclic_phase(
    mode: str,
    pair_size: int,
    cycle_duration: float,
    total_duration: float,
    cooldown: float,
) -> None:
    phase = f"{mode}-cyclic"
    _log(
        f"=== Fase: ciclos repetidos ({mode}), {pair_size} conexion(es) por ciclo, "
        f"{cycle_duration:.0f}s de lectura por ciclo, cooldown {cooldown:.1f}s, "
        f"hasta {total_duration:.0f}s totales ==="
    )
    _require_healthy(phase, "inicio", "antes de empezar")

    groups = _channel_groups(pair_size)
    start = time.monotonic()
    cycle_num = 0
    total_frames = 0

    while time.monotonic() - start < total_duration:
        cycle_num += 1
        channels = groups[(cycle_num - 1) % len(groups)]
        elapsed_total = time.monotonic() - start

        clip_by_channel: dict[int, tuple[datetime, datetime]] = {}
        if mode == "rec":
            for ch in channels:
                clip = find_existing_clip(ch)
                if clip is not None:
                    clip_by_channel[ch] = clip
            channels = tuple(clip_by_channel.keys())
            if not channels:
                _log(f"  ciclo {cycle_num} [t={elapsed_total:5.0f}s]: ningun canal del grupo tiene grabaciones; se omite")
                continue

        results = [ChannelResult(channel=ch) for ch in channels]
        threads = []
        for ch, result in zip(channels, results):
            if mode == "live":
                url = _live_url(ch)
            else:
                clip_start, clip_end = clip_by_channel[ch]
                usable = max((clip_end - clip_start).total_seconds() - cycle_duration, 0)
                offset = random.uniform(0, usable) if usable > 0 else 0
                play_start = clip_start + timedelta(seconds=offset)
                url = _recording_url(ch, play_start, clip_end)
            thread = threading.Thread(target=_measure_stream, args=(url, ch, cycle_duration, result))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=cycle_duration + 35)

        frames_this_cycle = sum(r.frames_read for r in results)
        total_frames += frames_this_cycle
        opened_all = all(r.opened for r in results)
        status = "OK" if opened_all else "*** FALLO AL ABRIR ***"
        _log(f"  ciclo {cycle_num} [t={elapsed_total:5.0f}s] canales {channels}: {status}, {frames_this_cycle} frames")
        if not opened_all:
            for r in results:
                if not r.opened:
                    _log(f"    canal {r.channel}: {r.error} (tras {r.open_latency:.2f}s)")

        _require_healthy(phase, f"ciclo {cycle_num} (t={elapsed_total:.0f}s, canales {channels})", "despues de este ciclo")

        if cooldown > 0:
            time.sleep(cooldown)

    _log(f"=== Fase {phase} completa: {cycle_num} ciclos, {total_frames} frames totales, el DVR siguio respondiendo ===")


# -- orquestacion -----------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--phase",
        choices=[
            "live-concurrency",
            "rec-concurrency",
            "live-persistence",
            "rec-persistence",
            "live-cyclic",
            "rec-cyclic",
            "all",
        ],
        required=True,
    )
    parser.add_argument("--levels", default="1,2,3,4", help="niveles de concurrencia a probar, ej. '1,2,3,4' o '3,4' para reanudar")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="segundos por nivel (concurrencia), de la fase completa (persistencia), o duracion TOTAL (ciclica)",
    )
    parser.add_argument("--channel", type=int, default=1, help="canal a usar en las fases de persistencia")
    parser.add_argument("--sample-interval", type=float, default=30.0, help="cada cuantos segundos se muestrea en persistencia")
    parser.add_argument(
        "--paced",
        action="store_true",
        help="en grabaciones, reproduce a la velocidad real del clip (como hace la app) en vez de a maxima velocidad",
    )
    parser.add_argument("--pair-size", type=int, default=2, help="conexiones simultaneas por ciclo, en la fase ciclica")
    parser.add_argument("--cycle-duration", type=float, default=3.0, help="segundos de lectura por ciclo, en la fase ciclica")
    parser.add_argument("--cooldown", type=float, default=1.0, help="pausa entre ciclos, en la fase ciclica")
    args = parser.parse_args()

    _open_log_file()
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    try:
        if args.phase in ("live-concurrency", "all"):
            run_concurrency_phase("live", levels, args.duration or 8.0)
        if args.phase in ("rec-concurrency", "all"):
            run_concurrency_phase("rec", levels, args.duration or 8.0, paced=args.paced)
        if args.phase in ("live-persistence", "all"):
            run_persistence_phase("live", args.channel, args.duration or 300.0, args.sample_interval)
        if args.phase in ("rec-persistence", "all"):
            run_persistence_phase("rec", args.channel, args.duration or 300.0, args.sample_interval)
        if args.phase in ("live-cyclic", "all"):
            run_cyclic_phase("live", args.pair_size, args.cycle_duration, args.duration or 300.0, args.cooldown)
        if args.phase in ("rec-cyclic", "all"):
            run_cyclic_phase("rec", args.pair_size, args.cycle_duration, args.duration or 300.0, args.cooldown)
    except BreakpointFound as bp:
        _log("")
        _log("=" * 70)
        _log(f"*** PUNTO DE FALLA ENCONTRADO: fase={bp.phase} nivel={bp.level} ***")
        _log(f"*** {bp.health.detail} (tras {bp.health.elapsed:.2f}s) ***")
        _log("*** El DVR necesita reiniciarse manualmente antes de continuar. ***")
        _log("=" * 70)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
