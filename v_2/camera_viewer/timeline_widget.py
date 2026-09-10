from __future__ import annotations

import time as time_module
from datetime import date, datetime, time as dtime, timedelta

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsRectItem, QGraphicsSimpleTextItem

from .zoom_canvas import ZoomPanGraphicsView

SECONDS_PER_DAY = 24 * 60 * 60
BODY_HEIGHT = 40
AXIS_HEIGHT = 24
BOTTOM_PADDING = 8

MINUTE_TICK_STEPS = (1, 5, 10, 15, 30)
MINUTE_TICK_MIN_SPACING_PX = 6.0
MINUTE_TICK_COLOR = QColor("#1E293B")

# Orden explicito de capas: fondo, encima las lineas de minuto, y por
# ultimo el marcador de hora seleccionada.
Z_BACKGROUND = 0
Z_MINUTE_TICK = 1
Z_MARKER = 10

PLAYHEAD_REFRESH_MS = 200


def _cosmetic_pen(color: QColor) -> QPen:
    """Pen que siempre se ve de 1px en pantalla, sin importar el zoom
    horizontal aplicado (si no, los bordes se ven cada vez mas delgados a
    medida que se hace zoom, porque el pen normal escala con la vista)."""
    pen = QPen(color)
    pen.setCosmetic(True)
    return pen


class TimelineWidget(ZoomPanGraphicsView):
    """Linea de tiempo de 24h -- una sola franja, sin dividir por canal.
    Que haya o no grabacion disponible lo indica cada panel de camara en su
    propio estado al reproducir, no la linea de tiempo. Zoom horizontal con
    la rueda del mouse (el eje vertical no se toca); cuando el contenido no
    cabe, se recorre con la scrollbar horizontal -- deliberadamente sin
    arrastre (ScrollHandDrag), para que un clic normal siempre seleccione
    hora sin ambiguedad con un posible drag."""

    time_selected = Signal(datetime)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._day: date | None = None
        self._marker_item: QGraphicsLineItem | None = None
        self._minute_tick_items: list[QGraphicsLineItem] = []
        self._playhead_started_at: float | None = None
        self._playhead_started_time: datetime | None = None

        # Sin antialiasing a proposito: son formas planas (fondo, ticks),
        # y con el suavizado prendido dos rectangulos que comparten un
        # borde exacto dejaban una linea oscura de 1px entre ellos.
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        self._playhead_timer = QTimer(self)
        self._playhead_timer.setInterval(PLAYHEAD_REFRESH_MS)
        self._playhead_timer.timeout.connect(self._advance_playhead)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(BODY_HEIGHT + AXIS_HEIGHT + BOTTOM_PADDING)
        self._redraw()

    def _update_transform(self) -> None:
        # Zoom minimo (1.0) = el dia completo cabe en el ancho visible;
        # zoom > 1.0 amplia horas desde ahi. El eje vertical nunca escala.
        self.resetTransform()
        self.scale(self._fit_scale_x() * self._zoom, 1.0)
        self._refresh_minute_ticks()

    def _fit_scale_x(self) -> float:
        viewport_width = max(self.viewport().width(), 1)
        return viewport_width / SECONDS_PER_DAY

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_transform()

    def set_day(self, day: date) -> None:
        self._day = day
        self.stop_playhead()
        self.reset_zoom()
        self._redraw()

    def _redraw(self) -> None:
        scene = self.scene()
        scene.clear()
        self._marker_item = None
        self._minute_tick_items = []

        scene.setSceneRect(0, 0, SECONDS_PER_DAY, BODY_HEIGHT + AXIS_HEIGHT)

        if self._day is None:
            text = scene.addSimpleText("Selecciona un dia en el calendario para ver sus grabaciones.")
            text.setBrush(QBrush(QColor("#94A3B8")))
            text.setFlag(text.GraphicsItemFlag.ItemIgnoresTransformations, True)
            text.setPos(12, 12)
            return

        body = QGraphicsRectItem(0, 0, SECONDS_PER_DAY, BODY_HEIGHT)
        body.setBrush(QBrush(QColor("#111827")))
        body.setPen(_cosmetic_pen(QColor("#1F2937")))
        body.setZValue(Z_BACKGROUND)
        scene.addItem(body)

        axis_y = BODY_HEIGHT + 4
        for hour in range(25):
            x = hour * 3600
            tick = QGraphicsLineItem(x, axis_y, x, axis_y + 8)
            tick.setPen(_cosmetic_pen(QColor("#475569")))
            scene.addItem(tick)
            if hour < 24:
                label = QGraphicsSimpleTextItem(f"{hour:02d}:00")
                label.setBrush(QBrush(QColor("#94A3B8")))
                label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations, True)
                label.setPos(x, axis_y + 8)
                scene.addItem(label)

        self._refresh_minute_ticks()

    def _refresh_minute_ticks(self) -> None:
        """Lineas finas cada minuto, para orientarse mejor al hacer zoom --
        se ocultan progresivamente (y por completo si hace falta) al alejar
        el zoom, para que nunca se amontonen."""
        scene = self.scene()
        for item in self._minute_tick_items:
            scene.removeItem(item)
        self._minute_tick_items = []

        if self._day is None:
            return

        step = self._minute_tick_step()
        if step is None:
            return

        pen = _cosmetic_pen(MINUTE_TICK_COLOR)
        for minute in range(0, 24 * 60, step):
            if minute % 60 == 0:
                continue  # ya existe la linea de hora
            x = minute * 60
            tick = QGraphicsLineItem(x, 0, x, BODY_HEIGHT)
            tick.setPen(pen)
            tick.setZValue(Z_MINUTE_TICK)
            scene.addItem(tick)
            self._minute_tick_items.append(tick)

    def _minute_tick_step(self) -> int | None:
        pixels_per_minute = self._fit_scale_x() * self._zoom * 60
        for step in MINUTE_TICK_STEPS:
            if pixels_per_minute * step >= MINUTE_TICK_MIN_SPACING_PX:
                return step
        return None

    def _seconds_since_midnight(self, moment: datetime) -> int:
        midnight = datetime.combine(moment.date(), dtime.min)
        return int((moment - midnight).total_seconds())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._day is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        seconds = max(0, min(SECONDS_PER_DAY - 1, int(scene_pos.x())))
        selected = datetime.combine(self._day, dtime.min) + timedelta(seconds=seconds)
        self._draw_marker(seconds)
        self.time_selected.emit(selected)
        event.accept()

    def _draw_marker(self, seconds: int) -> None:
        scene = self.scene()
        if self._marker_item is not None:
            scene.removeItem(self._marker_item)

        line = QGraphicsLineItem(seconds, 0, seconds, BODY_HEIGHT)
        pen = _cosmetic_pen(QColor("#F8FAFC"))
        pen.setWidth(2)
        line.setPen(pen)
        line.setZValue(Z_MARKER)
        scene.addItem(line)
        self._marker_item = line

    # -- marcador que avanza junto con la reproduccion ---------------------

    def start_playhead(self, selected_time: datetime) -> None:
        """Arranca el marcador avanzando en tiempo real desde
        selected_time -- asume reproduccion a velocidad 1x (igual que la
        del DVR), no rastrea el frame exacto de cada canal por separado."""
        self._playhead_started_at = time_module.monotonic()
        self._playhead_started_time = selected_time
        self._draw_marker(self._seconds_since_midnight(selected_time))
        self._playhead_timer.start()

    def stop_playhead(self) -> None:
        self._playhead_timer.stop()
        self._playhead_started_at = None
        self._playhead_started_time = None

    def _advance_playhead(self) -> None:
        if self._playhead_started_at is None or self._playhead_started_time is None or self._day is None:
            return

        elapsed = time_module.monotonic() - self._playhead_started_at
        current_time = self._playhead_started_time + timedelta(seconds=elapsed)
        if current_time.date() != self._day:
            self.stop_playhead()
            return

        seconds = self._seconds_since_midnight(current_time)
        if seconds >= SECONDS_PER_DAY:
            self.stop_playhead()
            return

        self._draw_marker(seconds)
