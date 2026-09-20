from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .export_clip import (
    PHASE_CONVERTING,
    PHASE_DOWNLOADING,
    PHASE_QUEUED,
    PHASE_RETRYING,
    PHASE_VERIFYING,
    ClipRange,
    estimate_bytes,
)

# Estado del avance de una exportación, para mostrarlo (save_progress_dialog.py). Sin
# ventanas: ExportFlow lo alimenta con los avisos del hilo de exportación y la ventana
# solo lo lee; así se prueba sin abrir nada. El total de bytes de una descarga NO lo
# anuncia el DVR: se estima (`estimate_bytes`), así que el porcentaje es aproximado y
# nunca pasa de 99 % hasta que el archivo realmente termina.

PHASE_DONE = "done"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"
FINAL_PHASES = (PHASE_DONE, PHASE_FAILED, PHASE_CANCELLED)

SPEED_WINDOW = 5.0  # s sobre los que se mide la velocidad (un atasco del DVR se nota, sin dar saltos)
MIN_SPEED_SPAN = 1.0  # s mínimos de muestras para dar una velocidad
MIN_ETA_ELAPSED = 3.0  # s antes de arriesgar un tiempo restante global
MAX_DOWNLOAD_FRACTION = 0.99  # la descarga no llega a 100 % sola: falta que el archivo termine

# Cuánto pesa cada fase en el avance de UN canal (la descarga es casi todo).
DOWNLOAD_WEIGHT = 0.90
PHASE_FLOOR = {PHASE_CONVERTING: 0.92, PHASE_VERIFYING: 0.97}


@dataclass
class ChannelProgress:
    channel: int
    phase: str = PHASE_QUEUED
    text: str = "En cola…"
    bytes_done: int = 0
    samples: deque = field(default_factory=lambda: deque(maxlen=400))  # (instante, bytes)
    result_path: str | None = None
    result_size: int | None = None
    warning: str | None = None
    error: str | None = None

    @property
    def is_final(self) -> bool:
        return self.phase in FINAL_PHASES


class ExportProgress(QObject):
    changed = Signal()

    def __init__(
        self,
        clip_range: ClipRange,
        folder: Path,
        channels: list[int],
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.clip_range = clip_range
        self.folder = Path(folder)
        self.channels = list(channels)
        self._clock = clock
        self._by_channel = {channel: ChannelProgress(channel) for channel in channels}
        self.expected_bytes = estimate_bytes(clip_range, 1)  # por canal
        self.started_at = clock()
        self.finished_at: float | None = None
        self.cancelling = False  # el usuario pidió cancelar (puede tardar en cortarse)

    # -- alimentado por ExportFlow ---------------------------------------------------------

    def channel(self, channel: int) -> ChannelProgress:
        return self._by_channel[channel]

    def set_phase(self, channel: int, phase: str | None, text: str) -> None:
        item = self._by_channel[channel]
        if item.is_final:
            return
        item.text = text
        if phase is None:
            return
        if phase == PHASE_RETRYING:
            item.bytes_done = 0
            item.samples.clear()
        item.phase = phase

    def set_bytes(self, channel: int, received: int) -> None:
        item = self._by_channel[channel]
        if item.phase not in (PHASE_QUEUED, PHASE_RETRYING, PHASE_DOWNLOADING):
            return
        if item.phase != PHASE_DOWNLOADING or received < item.bytes_done:  # arrancó (o volvió a empezar)
            item.samples.clear()
        item.phase = PHASE_DOWNLOADING
        item.text = "Descargando…"
        item.bytes_done = received
        item.samples.append((self._clock(), received))

    def mark_done(self, channel: int, path: str, size: int | None, warning: str | None) -> None:
        item = self._by_channel[channel]
        item.phase, item.text = PHASE_DONE, "Listo"
        item.result_path, item.result_size, item.warning = path, size, warning

    def mark_failed(self, channel: int, message: str, cancelled: bool) -> None:
        item = self._by_channel[channel]
        item.phase = PHASE_CANCELLED if cancelled else PHASE_FAILED
        item.text = message
        item.error = message

    def request_cancel(self) -> None:
        self.cancelling = True

    def finish(self) -> None:
        self.finished_at = self._clock()

    # -- lectura ------------------------------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def saved_count(self) -> int:
        return sum(1 for item in self._by_channel.values() if item.phase == PHASE_DONE)

    def total_count(self) -> int:
        return len(self._by_channel)

    def was_cancelled(self) -> bool:
        return any(item.phase == PHASE_CANCELLED for item in self._by_channel.values())

    def bytes_downloaded(self) -> int:
        return sum(item.bytes_done for item in self._by_channel.values())

    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else self._clock()
        return max(0.0, end - self.started_at)

    def fraction(self, channel: int) -> float:
        """Avance de un canal (0–1): descarga hasta 0.90, luego convertir y verificar."""
        item = self._by_channel[channel]
        if item.is_final:
            return 1.0
        if item.phase in PHASE_FLOOR:
            return PHASE_FLOOR[item.phase]
        if item.phase == PHASE_DOWNLOADING and self.expected_bytes > 0:
            return DOWNLOAD_WEIGHT * min(MAX_DOWNLOAD_FRACTION, item.bytes_done / self.expected_bytes)
        return 0.0

    def download_fraction(self, channel: int) -> float:
        """Solo de la descarga (0–0.99, o 1 si ya la pasó)."""
        item = self._by_channel[channel]
        if item.phase in (PHASE_CONVERTING, PHASE_VERIFYING) or item.is_final:
            return 1.0
        if self.expected_bytes <= 0:
            return 0.0
        return min(MAX_DOWNLOAD_FRACTION, item.bytes_done / self.expected_bytes)

    def overall_fraction(self) -> float:
        if not self._by_channel:
            return 1.0
        return sum(self.fraction(channel) for channel in self._by_channel) / len(self._by_channel)

    def speed(self, channel: int) -> float | None:
        """Bytes/s recibidos en los últimos SPEED_WINDOW s (0 si se atascó); None si aún no hay datos."""
        item = self._by_channel[channel]
        if item.phase != PHASE_DOWNLOADING or not item.samples:
            return None
        now = self._clock()
        baseline = item.samples[0]
        for sample in item.samples:
            if now - sample[0] >= SPEED_WINDOW:
                baseline = sample  # la última muestra fuera de la ventana
            else:
                break
        span = now - baseline[0]
        if span < MIN_SPEED_SPAN:
            return None
        return max(0.0, (item.bytes_done - baseline[1]) / span)

    def eta(self, channel: int) -> float | None:
        """Segundos que faltan de descarga de un canal, o None si no se puede saber."""
        item = self._by_channel[channel]
        speed = self.speed(channel)
        remaining = self.expected_bytes - item.bytes_done
        if speed is None or speed <= 0 or remaining <= 0:
            return None
        return remaining / speed

    def overall_eta(self) -> float | None:
        fraction = self.overall_fraction()
        elapsed = self.elapsed()
        if self.finished or fraction < 0.03 or elapsed < MIN_ETA_ELAPSED:
            return None
        return elapsed * (1 - fraction) / fraction
