from __future__ import annotations

import time as time_module
from datetime import date, datetime, time as dtime, timedelta

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsRectItem, QGraphicsSimpleTextItem, QScrollBar

from .dvr_client import Clip
from .zoom_canvas import ZoomPanGraphicsView

SECONDS_PER_DAY = 24 * 60 * 60
BODY_HEIGHT = 40
AXIS_HEIGHT = 24
BOTTOM_PADDING = 8

MINUTE_TICK_STEPS = (1, 5, 10, 15, 30)
MINUTE_TICK_MIN_SPACING_PX = 6.0
MINUTE_TICK_COLOR = QColor("#1E293B")

# Categorias de etiquetas HH:MM intermedias, en el orden en que se van
# activando conforme hay mas zoom. Cada nivel es su propio conjunto
# COMPLETO (no un incremento sobre el anterior): al pasar de "cuartos" a
# "diez en diez" hay que dejar de mostrar :15/:45, porque mezclados con
# :10/:20/:40/:50 el espaciado se ve inconsistente (5,5,10,10,5,5,10 en vez
# de 10,10,10,10,10,10).
MINUTE_LABEL_LEVELS: tuple[frozenset[int], ...] = (
    frozenset({30}),
    frozenset({15, 30, 45}),
    frozenset({10, 20, 30, 40, 50}),
    frozenset(range(1, 60)),
)
MINUTE_LABEL_COLOR = QColor("#94A3B8")
MINUTE_LABEL_TICK_COLOR = QColor("#475569")
# Aire minimo entre el final de una etiqueta y el comienzo de la
# siguiente, ademas de su propio ancho de texto.
MINUTE_LABEL_MARGIN_PX = 4.0
# Alto de la rayita corta que cuelga de cada etiqueta (hora o minuto) hacia
# la barra de color, señalando su punto exacto en el tiempo.
AXIS_TICK_HEIGHT = 8

# Tramos sin grabacion en NINGUN canal -- rojo apagado, encima del fondo
# pero debajo de los ticks de minuto (que deben seguir viendose sobre el
# tramo rojo igual que sobre el resto de la barra).
GAP_COLOR = QColor(220, 38, 38, 110)

# Orden explicito de capas: fondo, encima los tramos sin grabacion, encima
# las lineas de minuto, y por ultimo el marcador de hora seleccionada.
Z_BACKGROUND = 0
Z_GAP = 0.5
Z_MINUTE_TICK = 1
Z_RANGE = 5  # banda del clip a exportar: sobre los huecos y las marcas de minuto, bajo el cursor
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
    hora sin ambiguedad con un posible drag.

    La franja de horas (ticks + etiquetas) va ARRIBA de la barra de color,
    no abajo: la scrollbar horizontal vive en el borde inferior del
    viewport, y flota encima del contenido en vez de reservar su propio
    espacio (ver _setup_overlay_scrollbar) -- si las horas estuvieran
    abajo, la scrollbar las taparia a la mitad al aparecer."""

    time_selected = Signal(datetime)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._day: date | None = None
        self._marker_item: QGraphicsLineItem | None = None
        self._minute_tick_items: list[QGraphicsLineItem] = []
        self._minute_label_items: list[QGraphicsLineItem | QGraphicsSimpleTextItem] = []
        self._minute_label_width: float | None = None
        self._clips_by_channel: dict[int, list[Clip]] = {}
        self._gap_items: list[QGraphicsRectItem] = []
        self._export_range: tuple[datetime, datetime] | None = None
        self._range_item: QGraphicsRectItem | None = None
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

        self._setup_overlay_scrollbar()
        self._redraw()

    def _setup_overlay_scrollbar(self) -> None:
        """La scrollbar horizontal REAL de QAbstractScrollArea siempre
        reserva su propio espacio en el viewport cuando esta visible --
        aunque se reparente a otro widget, Qt sigue encogiendo el viewport
        en base a ELLA, no a quien sea su padre visual (verificado
        renderizando: seguia encogiendose igual). La unica forma de que
        nunca robe espacio es apagarla del todo (AlwaysOff, invisible
        siempre) y poner en su lugar una QScrollBar propia, flotando sobre
        el viewport, que solo espeja su rango/valor -- puramente cosmetica
        e interactiva, el layout nunca la toma en cuenta."""
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        real_bar = self.horizontalScrollBar()

        self._overlay_scrollbar = QScrollBar(Qt.Orientation.Horizontal, self.viewport())
        self._overlay_scrollbar.setRange(real_bar.minimum(), real_bar.maximum())
        self._overlay_scrollbar.setPageStep(real_bar.pageStep())
        self._overlay_scrollbar.setValue(real_bar.value())
        self._overlay_scrollbar.setVisible(real_bar.maximum() > real_bar.minimum())

        real_bar.rangeChanged.connect(self._sync_overlay_scrollbar_range)
        real_bar.valueChanged.connect(self._overlay_scrollbar.setValue)
        self._overlay_scrollbar.valueChanged.connect(real_bar.setValue)

        self._position_overlay_scrollbar()

    def _sync_overlay_scrollbar_range(self, minimum: int, maximum: int) -> None:
        self._overlay_scrollbar.setRange(minimum, maximum)
        self._overlay_scrollbar.setPageStep(self.horizontalScrollBar().pageStep())
        self._overlay_scrollbar.setVisible(maximum > minimum)

    def _update_transform(self) -> None:
        # Zoom minimo (1.0) = el dia completo cabe en el ancho visible;
        # zoom > 1.0 amplia horas desde ahi. El eje vertical nunca escala.
        self.resetTransform()
        self.scale(self._fit_scale_x() * self._zoom, 1.0)
        self._refresh_minute_ticks()
        self._refresh_minute_labels()

    def _fit_scale_x(self) -> float:
        viewport_width = max(self.viewport().width(), 1)
        return viewport_width / SECONDS_PER_DAY

    def _position_overlay_scrollbar(self) -> None:
        viewport = self.viewport()
        height = self._overlay_scrollbar.sizeHint().height()
        self._overlay_scrollbar.setGeometry(0, viewport.height() - height, viewport.width(), height)
        self._overlay_scrollbar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_transform()
        self._position_overlay_scrollbar()

    @property
    def day(self) -> date | None:
        return self._day

    def clear_marker(self) -> None:
        """Quita la linea blanca (marcador/cursor) sin tocar nada mas."""
        if self._marker_item is not None:
            self.scene().removeItem(self._marker_item)
            self._marker_item = None

    def set_day(self, day: date) -> None:
        self._day = day
        # Se limpia hasta que lleguen los clips del dia nuevo (main_window
        # los pide en cuanto se selecciona el dia) -- sin esto se verian
        # por un instante los huecos del dia anterior, que no tienen nada
        # que ver con este.
        self._clips_by_channel = {}
        self.stop_playhead()
        self.reset_zoom()
        self._redraw()

    def set_clips(self, clips_by_channel: dict[int, list[Clip]]) -> None:
        self._clips_by_channel = clips_by_channel
        self._refresh_gaps()

    def _redraw(self) -> None:
        scene = self.scene()
        scene.clear()
        self._marker_item = None
        self._range_item = None
        self._minute_tick_items = []
        self._minute_label_items = []
        self._gap_items = []

        scene.setSceneRect(0, 0, SECONDS_PER_DAY, BODY_HEIGHT + AXIS_HEIGHT)

        if self._day is None:
            text = scene.addSimpleText("Selecciona un día en el calendario para ver sus grabaciones.")
            text.setBrush(QBrush(QColor("#94A3B8")))
            text.setFlag(text.GraphicsItemFlag.ItemIgnoresTransformations, True)
            text.setPos(12, 12)
            return

        body = QGraphicsRectItem(0, AXIS_HEIGHT, SECONDS_PER_DAY, BODY_HEIGHT)
        body.setBrush(QBrush(QColor("#111827")))
        body.setPen(_cosmetic_pen(QColor("#1F2937")))
        body.setZValue(Z_BACKGROUND)
        scene.addItem(body)

        # Etiqueta arriba, tick colgando hacia abajo hasta tocar la barra de
        # color -- ver el docstring de la clase sobre por que la franja de
        # horas va arriba y no abajo.
        tick_top = AXIS_HEIGHT - AXIS_TICK_HEIGHT
        for hour in range(25):
            x = hour * 3600
            tick = QGraphicsLineItem(x, tick_top, x, AXIS_HEIGHT)
            tick.setPen(_cosmetic_pen(QColor("#475569")))
            scene.addItem(tick)
            if hour < 24:
                label = QGraphicsSimpleTextItem(f"{hour:02d}:00")
                label.setBrush(QBrush(QColor("#94A3B8")))
                label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations, True)
                label.setPos(x, 0)
                scene.addItem(label)

        self._refresh_minute_ticks()
        self._refresh_minute_labels()
        self._refresh_gaps()
        self._draw_export_range()

    # -- banda del clip a exportar ------------------------------------------------------

    def set_export_range(self, start: datetime, end: datetime) -> None:
        """Pinta la banda del rango marcado para exportar (solo el tramo que cae en el día mostrado)."""
        self._export_range = (start, end)
        self._draw_export_range()

    def clear_export_range(self) -> None:
        self._export_range = None
        self._draw_export_range()

    def _draw_export_range(self) -> None:
        scene = self.scene()
        if self._range_item is not None:
            try:
                scene.removeItem(self._range_item)
            except RuntimeError:  # la escena ya lo borró (scene.clear en _redraw)
                pass
            self._range_item = None
        if self._export_range is None or self._day is None:
            return
        midnight = datetime.combine(self._day, dtime.min)
        start = max(0.0, (self._export_range[0] - midnight).total_seconds())
        end = min(float(SECONDS_PER_DAY), (self._export_range[1] - midnight).total_seconds())
        if end <= start:
            return
        band = QGraphicsRectItem(start, AXIS_HEIGHT, end - start, BODY_HEIGHT)
        band.setBrush(QBrush(QColor(59, 130, 246, 110)))
        band.setPen(_cosmetic_pen(QColor("#3B82F6")))
        band.setZValue(Z_RANGE)
        scene.addItem(band)
        self._range_item = band

    def _refresh_gaps(self) -> None:
        """Tramos del dia sin grabacion en NINGUN canal -- el complemento
        de la union de los rangos de las 4 camaras. Se recalcula entero
        cada vez (clips nuevos o dia distinto) en vez de tratar de
        actualizar incrementalmente; con a lo mas unas pocas docenas de
        clips por dia el costo es insignificante."""
        scene = self.scene()
        for item in self._gap_items:
            scene.removeItem(item)
        self._gap_items = []

        if self._day is None:
            return

        pen = _cosmetic_pen(GAP_COLOR)
        for start_seconds, end_seconds in self._gap_seconds():
            rect = QGraphicsRectItem(start_seconds, AXIS_HEIGHT, end_seconds - start_seconds, BODY_HEIGHT)
            rect.setBrush(QBrush(GAP_COLOR))
            rect.setPen(pen)
            rect.setZValue(Z_GAP)
            scene.addItem(rect)
            self._gap_items.append(rect)

    def _gap_seconds(self) -> list[tuple[int, int]]:
        """Complemento, dentro de [0, SECONDS_PER_DAY), de la union de
        clips de todos los canales -- ver _covered_seconds()."""
        gaps: list[tuple[int, int]] = []
        cursor = 0
        for start, end in self._covered_seconds():
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < SECONDS_PER_DAY:
            gaps.append((cursor, SECONDS_PER_DAY))
        return gaps

    def _covered_seconds(self) -> list[tuple[int, int]]:
        """Rangos (en segundos desde medianoche) con grabacion en AL MENOS
        un canal, fusionados y ordenados. Cada clip se recorta a los
        limites del dia mostrado -- un clip de otro dia (no deberia pasar,
        pero por las dudas) no debe ensuciar el resultado."""
        if self._day is None:
            return []

        day_start = datetime.combine(self._day, dtime.min)
        day_end = day_start + timedelta(days=1)

        intervals: list[tuple[int, int]] = []
        for clips in self._clips_by_channel.values():
            for clip in clips:
                start = max(clip.start, day_start)
                end = min(clip.end, day_end)
                if end <= start:
                    continue
                # Offset directo contra day_start, NO _seconds_since_midnight:
                # un clip puede terminar exactamente a medianoche del dia
                # SIGUIENTE (el ultimo bloque de un dia grabado completo, ver
                # schedule.py del emulador) -- ese helper usa moment.date(),
                # que en ese caso exacto da el dia siguiente y devuelve 0 en
                # vez de SECONDS_PER_DAY, partiendo mal el ultimo tramo.
                start_seconds = int((start - day_start).total_seconds())
                end_seconds = int((end - day_start).total_seconds())
                intervals.append((start_seconds, end_seconds))

        if not intervals:
            return []

        intervals.sort()
        merged = [intervals[0]]
        for start, end in intervals[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

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
            tick = QGraphicsLineItem(x, AXIS_HEIGHT, x, AXIS_HEIGHT + BODY_HEIGHT)
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

    def _refresh_minute_labels(self) -> None:
        """Etiquetas HH:MM intermedias (media hora, cuartos, diez en diez,
        cada minuto), activandose progresivamente conforme el zoom deja
        espacio -- ver MINUTE_LABEL_LEVELS. Cada nivel es su propio
        conjunto completo (no se acumulan los anteriores), para que el
        espaciado entre marcas sea siempre uniforme."""
        scene = self.scene()
        for item in self._minute_label_items:
            scene.removeItem(item)
        self._minute_label_items = []

        if self._day is None:
            return

        level_index = self._active_minute_label_level()
        if level_index < 0:
            return

        minutes = sorted(MINUTE_LABEL_LEVELS[level_index])
        tick_top = AXIS_HEIGHT - AXIS_TICK_HEIGHT
        tick_pen = _cosmetic_pen(MINUTE_LABEL_TICK_COLOR)
        for hour in range(24):
            for minute in minutes:
                x = hour * 3600 + minute * 60

                # Misma rayita corta que ya tienen las horas (ver _redraw),
                # para que cada etiqueta nueva tambien señale su punto
                # exacto en vez de quedar flotando sin marca.
                tick = QGraphicsLineItem(x, tick_top, x, AXIS_HEIGHT)
                tick.setPen(tick_pen)
                scene.addItem(tick)
                self._minute_label_items.append(tick)

                label = QGraphicsSimpleTextItem(f"{hour:02d}:{minute:02d}")
                label.setBrush(QBrush(MINUTE_LABEL_COLOR))
                label.setFlag(label.GraphicsItemFlag.ItemIgnoresTransformations, True)
                label.setPos(x, 0)
                label.setZValue(Z_MINUTE_TICK)
                scene.addItem(label)
                self._minute_label_items.append(label)

    def _active_minute_label_level(self) -> int:
        """Indice del nivel de MINUTE_LABEL_LEVELS mas fino que todavia cabe
        sin superponerse, o -1 si ni el primero (media hora) cabe. "Cabe"
        se mide contra el hueco mas chico entre dos marcas consecutivas de
        ESE nivel (mas la del ":00", que ya se dibuja aparte en _redraw).
        Los niveles requieren cada vez menos espacio (30, 15, 10, 1 minuto
        de hueco minimo), asi que en cuanto uno no cabe, ninguno mas fino
        tampoco cabria."""
        pixels_per_minute = self._fit_scale_x() * self._zoom * 60
        required_px = self._minute_label_width_px() + MINUTE_LABEL_MARGIN_PX

        active = -1
        for level_index, level in enumerate(MINUTE_LABEL_LEVELS):
            gap_minutes = self._min_gap_minutes({0} | level)
            if pixels_per_minute * gap_minutes < required_px:
                break
            active = level_index
        return active

    @staticmethod
    def _min_gap_minutes(minutes: set[int]) -> int:
        ordered = sorted(minutes)
        gaps = [b - a for a, b in zip(ordered, ordered[1:])]
        gaps.append(60 - ordered[-1] + ordered[0])  # de la ultima marca de la hora a la ":00" siguiente
        return min(gaps)

    def _minute_label_width_px(self) -> float:
        if self._minute_label_width is None:
            metrics = QFontMetrics(QGraphicsSimpleTextItem().font())
            self._minute_label_width = metrics.horizontalAdvance("00:00")
        return self._minute_label_width

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

        line = QGraphicsLineItem(seconds, AXIS_HEIGHT, seconds, AXIS_HEIGHT + BODY_HEIGHT)
        pen = _cosmetic_pen(QColor("#F8FAFC"))
        pen.setWidth(2)
        line.setPen(pen)
        line.setZValue(Z_MARKER)
        scene.addItem(line)
        self._marker_item = line

    # -- marcador que avanza junto con la reproduccion ---------------------

    def draw_playhead(self, moment: datetime) -> None:
        """Dibuja el cursor en la hora `moment` (grabaciones: MainWindow lo mueve
        con el reloj compartido de la reproducción, ver playback_control.py).
        No hace nada si esa hora no cae en el día que se muestra."""
        if self._day is None or moment.date() != self._day:
            return
        self._draw_marker(self._seconds_since_midnight(moment))

    def start_playhead(self, selected_time: datetime) -> None:
        """Vista en vivo: el cursor avanza solo, en tiempo real, desde selected_time."""
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
