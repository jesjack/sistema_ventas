from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .clip import Clip

# Línea de tiempo propia de la ventana de guardado: muestra SOLO el clip elegido
# con un poco de contexto a cada lado (para poder alargarlo), el cursor de la
# reproducción, y dos asas para ajustar el inicio y el fin. Misma interfaz
# (set_export_range / clear_export_range) que la línea de tiempo del día, así que
# ExportFlow funciona con las dos.

HEIGHT = 74
AXIS_HEIGHT = 22
BAR_TOP = 26
BAR_HEIGHT = 34
HANDLE_HIT = 8  # píxeles alrededor de un asa en los que se considera "agarrada"
MIN_TICK_SPACING = 78  # píxeles mínimos entre marcas de la escala
TICK_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)

COLOR_BAR = QColor("#111827")
COLOR_COVERAGE = QColor("#334155")
COLOR_GAP = QColor(127, 29, 29, 150)
COLOR_RANGE = QColor(59, 130, 246, 105)
COLOR_HANDLE = QColor("#60A5FA")
COLOR_PLAYHEAD = QColor("#F8FAFC")
COLOR_AXIS = QColor("#94A3B8")
COLOR_TICK = QColor("#475569")


class ClipTimeline(QWidget):
    seek_requested = Signal(object)  # datetime al que ir (clic o arrastre sobre la barra)
    range_changed = Signal(object, object)  # (inicio, fin) tras arrastrar un asa

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._context: tuple[datetime, datetime] | None = None
        self._range: tuple[datetime, datetime] | None = None
        self._playhead: datetime | None = None
        self._coverage: list[tuple[datetime, datetime]] = []
        self._drag: str | None = None  # "start" | "end" | "seek"
        self._drag_range: tuple[datetime, datetime] | None = None

    # -- datos -----------------------------------------------------------------------------

    def set_context(self, start: datetime, end: datetime) -> None:
        """Tramo total que se muestra (el clip más un margen); el clip no puede salir de él."""
        self._context = (start, end)
        self.update()

    def context(self) -> tuple[datetime, datetime] | None:
        return self._context

    def set_coverage(self, clips_by_channel: dict[int, list[Clip]]) -> None:
        """Dónde hay grabación en al menos un canal; el resto se pinta como "sin grabación"."""
        spans = sorted((clip.start, clip.end) for clips in clips_by_channel.values() for clip in clips)
        merged: list[tuple[datetime, datetime]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        self._coverage = merged
        self.update()

    def set_export_range(self, start: datetime, end: datetime) -> None:
        self._range = (start, end)
        self.update()

    def clear_export_range(self) -> None:
        self._range = None
        self.update()

    def export_range(self) -> tuple[datetime, datetime] | None:
        return self._range

    def draw_playhead(self, moment: datetime) -> None:
        self._playhead = moment
        self.update()

    # -- geometría ----------------------------------------------------------------------------

    def _span_seconds(self) -> float:
        if self._context is None:
            return 0.0
        return max(1e-6, (self._context[1] - self._context[0]).total_seconds())

    def _bar_width(self) -> float:
        return max(1.0, float(self.width()) - 2)

    def time_to_x(self, moment: datetime) -> float:
        if self._context is None:
            return 0.0
        fraction = (moment - self._context[0]).total_seconds() / self._span_seconds()
        return 1 + fraction * self._bar_width()

    def x_to_time(self, x: float) -> datetime:
        if self._context is None:
            return datetime.min
        fraction = min(1.0, max(0.0, (x - 1) / self._bar_width()))
        return self._context[0] + timedelta(seconds=fraction * self._span_seconds())

    def _tick_step(self) -> int:
        per_second = self._bar_width() / self._span_seconds()
        for step in TICK_STEPS:
            if step * per_second >= MIN_TICK_SPACING:
                return step
        return TICK_STEPS[-1]

    # -- dibujo ------------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (nombre de Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if self._context is None:
            return
        width = self.width()
        painter.fillRect(QRectF(0, BAR_TOP, width, BAR_HEIGHT), COLOR_BAR)

        start, end = self._context
        for span_start, span_end in self._coverage:
            left = self.time_to_x(max(span_start, start))
            right = self.time_to_x(min(span_end, end))
            if right > left:
                painter.fillRect(QRectF(left, BAR_TOP, right - left, BAR_HEIGHT), COLOR_COVERAGE)
        # Lo que queda sin cubrir dentro del contexto: "sin grabación".
        cursor = start
        for span_start, span_end in self._coverage + [(end, end)]:
            gap_end = min(span_start, end)
            if gap_end > cursor:
                painter.fillRect(QRectF(self.time_to_x(cursor), BAR_TOP, self.time_to_x(gap_end) - self.time_to_x(cursor), BAR_HEIGHT), COLOR_GAP)
            cursor = max(cursor, min(span_end, end))

        self._paint_axis(painter)

        range_now = self._drag_range or self._range
        if range_now is not None:
            left, right = self.time_to_x(range_now[0]), self.time_to_x(range_now[1])
            painter.fillRect(QRectF(left, BAR_TOP, right - left, BAR_HEIGHT), COLOR_RANGE)
            painter.setPen(QPen(COLOR_HANDLE, 1))
            painter.drawRect(QRectF(left, BAR_TOP, right - left, BAR_HEIGHT - 1))
            for x in (left, right):
                painter.fillRect(QRectF(x - 2, BAR_TOP - 4, 4, BAR_HEIGHT + 8), COLOR_HANDLE)

        if self._playhead is not None and start <= self._playhead <= end:
            x = self.time_to_x(self._playhead)
            painter.setPen(QPen(COLOR_PLAYHEAD, 2))
            painter.drawLine(QPointF(x, BAR_TOP - 2), QPointF(x, BAR_TOP + BAR_HEIGHT + 2))

    def _paint_axis(self, painter: QPainter) -> None:
        start, end = self._context  # type: ignore[misc]
        step = self._tick_step()
        first = start.replace(microsecond=0)
        offset = (first - first.replace(hour=0, minute=0, second=0)).total_seconds()
        first_tick = first + timedelta(seconds=(-offset) % step)
        painter.setPen(QPen(COLOR_TICK, 1))
        moment = first_tick
        while moment <= end:
            x = self.time_to_x(moment)
            painter.drawLine(QPointF(x, AXIS_HEIGHT - 5), QPointF(x, BAR_TOP))
            painter.setPen(QPen(COLOR_AXIS, 1))
            painter.drawText(QPointF(x + 3, AXIS_HEIGHT - 7), f"{moment:%H:%M:%S}")
            painter.setPen(QPen(COLOR_TICK, 1))
            moment += timedelta(seconds=step)

    # -- ratón -------------------------------------------------------------------------------------

    def _handle_at(self, x: float) -> str | None:
        if self._range is None:
            return None
        start_x, end_x = self.time_to_x(self._range[0]), self.time_to_x(self._range[1])
        near_start, near_end = abs(x - start_x) <= HANDLE_HIT, abs(x - end_x) <= HANDLE_HIT
        if near_start and near_end:  # clip muy corto: se agarra el más cercano
            return "start" if abs(x - start_x) <= abs(x - end_x) else "end"
        return "start" if near_start else "end" if near_end else None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._context is None:
            return
        x = event.position().x()
        handle = self._handle_at(x)
        if handle is not None:
            self._drag, self._drag_range = handle, self._range
        else:
            self._drag = "seek"
            self.seek_requested.emit(self.x_to_time(x))
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._handle_at(x) else Qt.CursorShape.ArrowCursor)
            return
        moment = self.x_to_time(x)
        if self._drag == "seek":
            self.seek_requested.emit(moment)
        elif self._drag_range is not None:
            start, end = self._drag_range
            if self._drag == "start":
                start = min(moment, end - timedelta(seconds=1))
            else:
                end = max(moment, start + timedelta(seconds=1))
            self._drag_range = (start, end)
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag in ("start", "end") and self._drag_range is not None:
            start, end = self._drag_range
            self._drag_range = None
            if (start, end) != self._range:
                self.range_changed.emit(start, end)
        self._drag, self._drag_range = None, None
        self.update()
        event.accept()
