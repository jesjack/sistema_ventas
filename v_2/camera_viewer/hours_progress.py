from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .export_clip import ClipRange, estimate_bytes
from .export_hours import (
    PHASE_DOWNLOADING,
    PHASE_GAPS,
    PHASE_JOINING,
    ChannelPlan,
    HoursSpec,
    Piece,
)

# Estado del avance de una exportación de horas, para el botón "Exportar" y su panel. Sin ventanas:
# se alimenta con los avisos del motor (`apply`, ver export_hours.HoursExport) y las ventanas solo
# lo leen. El avance de un canal se mide en "trabajo": los segundos de video cuentan enteros, un tramo
# negro casi nada (es instantáneo), y unir el archivo final el último tramo.

PHASE_QUEUED = "queued"
PHASE_DONE = "done"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"
FINAL_PHASES = (PHASE_DONE, PHASE_FAILED, PHASE_CANCELLED)

GAP_WEIGHT = 0.02  # un segundo de negro pesa esto frente a un segundo de video
PIECES_SHARE = 0.93  # de una barra de canal: bajar/preparar las piezas; el resto es unir y verificar
JOINING_FRACTION = 0.95
SPEED_WINDOW = 8.0  # s para medir la velocidad de descarga
MIN_ETA_ELAPSED = 5.0  # s de trabajo antes de arriesgar un tiempo restante


@dataclass
class HoursChannel:
    channel: int
    pieces: tuple[Piece, ...] = ()
    phase: str = PHASE_QUEUED
    text: str = "En cola"
    current: int | None = None  # índice de la pieza de video que se está bajando
    done: set[int] = field(default_factory=set)
    piece_bytes: dict[int, int] = field(default_factory=dict)
    finished_bytes: int = 0
    warnings: list[str] = field(default_factory=list)
    result_path: str | None = None
    result_size: int | None = None
    note: str | None = None  # aviso al terminar (tramos negros, trozos perdidos...)
    error: str | None = None
    started_at: float | None = None

    @property
    def is_final(self) -> bool:
        return self.phase in FINAL_PHASES

    def weight(self, index: int) -> float:
        seconds = self.pieces[index].seconds
        return seconds if self.pieces[index].kind == "video" else max(0.5, seconds * GAP_WEIGHT)

    @property
    def total_work(self) -> float:
        return sum(self.weight(i) for i in range(len(self.pieces))) or 1.0

    @property
    def video_pieces(self) -> list[int]:
        return [i for i, piece in enumerate(self.pieces) if piece.kind == "video"]


class HoursProgress(QObject):
    changed = Signal()

    def __init__(
        self,
        spec: HoursSpec,
        plans: list[ChannelPlan],
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.folder = Path(spec.folder)
        self._clock = clock
        self.channels = [item.channel for item in plans]
        self._by_channel = {item.channel: HoursChannel(item.channel, item.pieces) for item in plans}
        self.started_at = clock()
        self.finished_at: float | None = None
        self.paused = False
        self.cancelling = False
        self._samples: deque[tuple[float, int]] = deque(maxlen=200)

    # -- alimentado por el controlador ---------------------------------------------------------------

    def channel(self, channel: int) -> HoursChannel:
        return self._by_channel[channel]

    def apply(self, event: tuple) -> None:
        kind = event[0]
        if kind == "paused":
            self.paused = bool(event[1])
        elif kind == "finished":
            self.finish()
        elif kind in ("plan", "state", "piece", "progress", "piece_done", "warning", "channel_done", "channel_failed"):
            item = self._by_channel.get(event[1])
            if item is None or item.is_final:
                return
            getattr(self, f"_on_{kind}")(item, event)

    def _on_plan(self, item: HoursChannel, event: tuple) -> None:
        item.started_at = item.started_at or self._clock()

    def _on_state(self, item: HoursChannel, event: tuple) -> None:
        item.text, phase = event[2], event[3]
        if item.phase in (PHASE_QUEUED, PHASE_DOWNLOADING, PHASE_GAPS, PHASE_JOINING):
            item.phase = phase if phase in (PHASE_DOWNLOADING, PHASE_GAPS, PHASE_JOINING) else item.phase
        item.started_at = item.started_at or self._clock()

    def _on_piece(self, item: HoursChannel, event: tuple) -> None:
        item.current = event[2]
        item.phase = PHASE_DOWNLOADING if item.phase == PHASE_QUEUED else item.phase

    def _on_progress(self, item: HoursChannel, event: tuple) -> None:
        index, received = event[2], event[3]
        item.piece_bytes[index] = received
        if item.phase == PHASE_QUEUED:
            item.phase = PHASE_DOWNLOADING
        self._samples.append((self._clock(), self.bytes_downloaded()))

    def _on_piece_done(self, item: HoursChannel, event: tuple) -> None:
        index = event[2]
        item.done.add(index)
        item.finished_bytes += item.piece_bytes.pop(index, 0)

    def _on_warning(self, item: HoursChannel, event: tuple) -> None:
        item.warnings.append(event[2])

    def _on_channel_done(self, item: HoursChannel, event: tuple) -> None:
        item.phase, item.text = PHASE_DONE, "Listo"
        item.result_path, item.note = event[2], event[3]
        try:
            item.result_size = Path(event[2]).stat().st_size
        except OSError:
            item.result_size = None

    def _on_channel_failed(self, item: HoursChannel, event: tuple) -> None:
        item.phase = PHASE_CANCELLED if event[2] == "Cancelado" else PHASE_FAILED
        item.text = item.error = event[2]

    def request_cancel(self) -> None:
        self.cancelling = True

    def finish(self) -> None:
        if self.finished_at is None:
            self.finished_at = self._clock()
            self.paused = False

    # -- lectura ---------------------------------------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def saved_count(self) -> int:
        return sum(1 for item in self._by_channel.values() if item.phase == PHASE_DONE)

    def total_count(self) -> int:
        return len(self._by_channel)

    def was_cancelled(self) -> bool:
        return any(item.phase == PHASE_CANCELLED for item in self._by_channel.values())

    def warnings_count(self) -> int:
        return sum(len(item.warnings) for item in self._by_channel.values())

    def bytes_downloaded(self) -> int:
        return sum(item.finished_bytes + sum(item.piece_bytes.values()) for item in self._by_channel.values())

    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else self._clock()
        return max(0.0, end - self.started_at)

    def pieces_fraction(self, channel: int) -> float:
        item = self._by_channel[channel]
        if not item.pieces:
            return 0.0
        work = sum(item.weight(i) for i in item.done)
        if item.current is not None and item.current not in item.done and item.current < len(item.pieces):
            expected = estimate_bytes(ClipRange(item.pieces[item.current].start, item.pieces[item.current].end), 1)
            got = item.piece_bytes.get(item.current, 0)
            if expected > 0:
                work += item.weight(item.current) * min(0.99, got / expected)
        return min(1.0, work / item.total_work)

    def fraction(self, channel: int) -> float:
        item = self._by_channel[channel]
        if item.is_final:
            return 1.0
        if item.phase == PHASE_JOINING:
            return JOINING_FRACTION
        return PIECES_SHARE * self.pieces_fraction(channel)

    def overall_fraction(self) -> float:
        if not self._by_channel:
            return 1.0
        weights = {channel: item.total_work for channel, item in self._by_channel.items()}
        total = sum(weights.values())
        return sum(self.fraction(channel) * weight for channel, weight in weights.items()) / total

    def speed(self) -> float | None:
        """Bytes/s recibidos del DVR en los últimos SPEED_WINDOW s (0 si se atascó); None sin datos."""
        if not self._samples or self.paused:
            return None
        now = self._clock()
        baseline = self._samples[0]
        for sample in self._samples:
            if now - sample[0] >= SPEED_WINDOW:
                baseline = sample
            else:
                break
        span = now - baseline[0]
        if span < 1.0:
            return None
        return max(0.0, (self.bytes_downloaded() - baseline[1]) / span)

    def overall_eta(self) -> float | None:
        fraction, elapsed = self.overall_fraction(), self.elapsed()
        if self.finished or self.paused or fraction < 0.01 or elapsed < MIN_ETA_ELAPSED:
            return None
        return elapsed * (1 - fraction) / fraction

    def piece_text(self, channel: int) -> str | None:
        """"09:14:00 · trozo 8 de 30", del trozo que se está bajando."""
        item = self._by_channel[channel]
        video = item.video_pieces
        if item.current is None or item.current not in video:
            return None
        return f"{item.pieces[item.current].start:%H:%M:%S} · trozo {video.index(item.current) + 1} de {len(video)}"

    def hours_text(self, channel: int) -> str:
        hours = sorted(self.spec.cells.get(channel, []))
        return ", ".join(f"{hour:02d}h" for hour in hours) if len(hours) <= 6 else f"{len(hours)} horas ({hours[0]:02d}h a {hours[-1] + 1:02d}h)"
