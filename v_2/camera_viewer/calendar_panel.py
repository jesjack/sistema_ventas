from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Alto maximo (no ancho: el ancho debe seguir al del resto de la columna
# -- inputs de ConnectionPanel, ver _build_ui en main_window.py -- para que
# calendario y campos queden alineados en vez de que el calendario se vea
# mas angosto que ellos).
MAX_HEIGHT = 260

# Separa visualmente el calendario del resto de la interfaz en vez de
# quedar pegado a sus bordes. Simetrico e igual al margen izquierdo/derecho
# que ya usa el form de ConnectionPanel (misma columna, ver
# connection_panel.py) -- si aqui es mas grande, el calendario se queda
# corto respecto al ancho real de los inputs/boton de abajo.
CONTENT_MARGINS = (4, 6, 4, 10)
FRAME_MARGIN = 4

# Colores de fin de semana (menos alarmante que el rojo por defecto de Qt)
# y de dias de otro mes (mismo gris que ya se usa en el resto de la app
# para texto secundario, ver TimelineWidget).
WEEKEND_COLOR = "#FBBF24"
OTHER_MONTH_COLOR = "#94A3B8"
SELECTED_COLOR = "#2563EB"
# Dia seleccionado sin ninguna grabacion: rojo en vez de azul, para que se
# note de inmediato que no hay nada que ver ahi.
SELECTED_EMPTY_COLOR = "#DC2626"
SELECTED_RADIUS = 6
# Debe coincidir con "QCalendarWidget QAbstractItemView { background-color:
# ... }" en __main__.py -- se repinta a mano antes del pill de seleccion
# porque la vista deja un cuadrado gris (su relleno de seleccion nativo,
# que no es redondeado) asomando detras de las esquinas del pill.
CELL_BACKGROUND = "#0B1120"

# Dias con grabacion disponible: pill claro (a proposito, para que
# contraste fuerte contra el resto del tema oscuro) con texto oscuro
# encima -- ni el gris de "otro mes" ni el ambar de fin de semana se leerian
# bien sobre este fondo, por eso el texto se fuerza a oscuro en estas celdas
# sin importar que dia de la semana sea.
RECORDED_COLOR = "#FDE68A"
RECORDED_TEXT_COLOR = "#0F172A"

# Recorrido de celdas de la grilla del calendario: siempre 6 semanas
# (42 dias), que es lo que QCalendarWidget efectivamente dibuja.
GRID_WEEKS = 6


def _selective_rounded_path(rect: QRectF, radius: float, round_left: bool, round_right: bool) -> QPainterPath:
    """Rectangulo con esquinas redondeadas solo en el lado izquierdo,
    derecho, ambos o ninguno -- para que una secuencia de dias consecutivos
    con grabacion se vea como una sola barra continua, redondeada nada mas
    en sus dos extremos reales (inicio/fin de secuencia), recta en todo lo
    demas (incluidos los cortes de fila).

    Truco: en vez de armar el contorno a mano con arcos, se extiende el
    rectangulo hacia el lado que NO debe redondearse (mas alla del borde
    real), se redondea ese rectangulo mas grande de forma uniforme, y se
    recorta con el rectangulo real -- los arcos del lado extendido quedan
    fuera del recorte, asi que ese lado sale recto."""
    if round_left and round_right:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path
    if not round_left and not round_right:
        path = QPainterPath()
        path.addRect(rect)
        return path

    if round_left:
        extended = QRectF(rect.x(), rect.y(), rect.width() + radius, rect.height())
    else:
        extended = QRectF(rect.x() - radius, rect.y(), rect.width() + radius, rect.height())

    rounded = QPainterPath()
    rounded.addRoundedRect(extended, radius, radius)
    clip = QPainterPath()
    clip.addRect(rect)
    return rounded.intersected(clip)


class _DateCellDelegate(QStyledItemDelegate):
    """Pinta a mano la fila de dias del mes (fila 0 de la tabla interna es
    el encabezado dom/lun/.../sab y se deja con el pintado normal):

    - Dias que no pertenecen al mes mostrado, opacados (por posicion de
      celda, no por fecha: QCalendarWidget.setDateTextFormat() resulto no
      pintarse para estas celdas en al menos algunas configuraciones de
      estilo/region -- se verifico renderizando que el dato quedaba
      guardado pero el pixel final no cambiaba).
    - El dia seleccionado, con esquinas redondeadas (QSS con el pseudo-
      estado ::item:selected tampoco se pinta en este widget).
    - Dias con grabacion disponible: una barra continua por cada tramo de
      dias consecutivos con grabacion, redondeada solo en el inicio/fin real
      de esa secuencia (ver _selective_rounded_path)."""

    def __init__(self, panel: "CalendarPanel", parent=None) -> None:
        super().__init__(parent)
        self._panel = panel

    def paint(self, painter, option, index) -> None:
        if index.row() == 0:
            super().paint(painter, option, index)
            return

        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_other_month = (index.row(), index.column()) in self._panel._other_month_cells
        cell_date = self._panel._cell_dates.get((index.row(), index.column()))
        is_recorded = (
            not is_other_month and cell_date is not None and cell_date in self._panel._recorded_days
        )

        painter.save()
        if is_selected and is_recorded:
            # El dia seleccionado tambien tiene grabacion: el azul toma la
            # FORMA que tendria el pill de disponibilidad en esta posicion
            # (recto en los lados donde la racha continua, redondeado solo
            # en un extremo real de esa racha) en vez de su propio radio fijo
            # -- para que se vea como el pill nada mas cambiando de color
            # ese dia, no como un cuadrado redondeado insertado a la fuerza
            # en medio de una barra continua.
            painter.fillRect(option.rect, QColor(CELL_BACKGROUND))
            round_left = (cell_date - timedelta(days=1)) not in self._panel._recorded_days
            round_right = (cell_date + timedelta(days=1)) not in self._panel._recorded_days
            radius = option.rect.height() / 2
            path = _selective_rounded_path(QRectF(option.rect), radius, round_left, round_right)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.fillPath(path, QColor(SELECTED_COLOR))
            text_color = QColor("white")
        elif is_selected:
            # Sin grabacion ese dia: rojo en vez de azul (ver
            # SELECTED_EMPTY_COLOR). Borra primero el relleno de seleccion
            # cuadrado que la vista ya pinto por su cuenta (nativo, sin
            # esquinas redondeadas) -- sin esto se asoma como un cuadrado
            # gris detras de las esquinas redondeadas del pill.
            painter.fillRect(option.rect, QColor(CELL_BACKGROUND))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(SELECTED_EMPTY_COLOR))
            painter.drawRoundedRect(option.rect, SELECTED_RADIUS, SELECTED_RADIUS)
            text_color = QColor("white")
        elif is_recorded:
            painter.fillRect(option.rect, QColor(CELL_BACKGROUND))
            round_left = (cell_date - timedelta(days=1)) not in self._panel._recorded_days
            round_right = (cell_date + timedelta(days=1)) not in self._panel._recorded_days
            radius = option.rect.height() / 2
            path = _selective_rounded_path(QRectF(option.rect), radius, round_left, round_right)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.fillPath(path, QColor(RECORDED_COLOR))
            text_color = QColor(RECORDED_TEXT_COLOR)
        elif is_other_month:
            text_color = QColor(OTHER_MONTH_COLOR)
        else:
            text_color = option.palette.color(QPalette.ColorRole.Text)

        painter.setPen(text_color)
        painter.setFont(option.font)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(index.data(Qt.ItemDataRole.DisplayRole)))
        painter.restore()


class CalendarPanel(QWidget):
    """Calendario real (grilla de dias, navegacion por mes) para elegir el
    dia a consultar -- no un input de texto con forma de fecha."""

    day_selected = Signal(date)
    month_changed = Signal(int, int)  # year, month -- para pedir sus dias con grabacion

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._other_month_cells: set[tuple[int, int]] = set()
        self._cell_dates: dict[tuple[int, int], date] = {}
        self._recorded_days: set[date] = set()

        self._calendar = QCalendarWidget(self)
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setMaximumDate(date.today())
        self._calendar.setMaximumHeight(MAX_HEIGHT)
        # Horizontal Expanding (no Maximum): que el calendario siga el ancho
        # real de la columna -- el mismo que toman los inputs de
        # ConnectionPanel -- en vez de quedar angosto a un ancho fijo que
        # ademas no alcanzaba para las 7 columnas sin recortarlas.
        self._calendar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._calendar.clicked.connect(self._on_selected)
        self._calendar.activated.connect(self._on_selected)
        self._calendar.currentPageChanged.connect(self._on_page_changed)
        # QCalendarWidget no expone setItemDelegate() directamente -- hay que
        # ponerlo en la QTableView interna que de verdad pinta las celdas.
        table_view = self._calendar.findChild(QTableView, "qt_calendar_calendarview")
        if table_view is not None:
            table_view.setItemDelegate(_DateCellDelegate(self, table_view))

        self._style_weekend_colors()
        self._hide_month_arrows()

        # QCalendarWidget ignora su propio "border"/"border-radius" de QSS
        # (verificado: no se pinta con ningun estilo) -- un QFrame alrededor
        # si lo respeta de forma confiable, que es para lo que existe.
        frame = QFrame(self)
        frame.setObjectName("calendarFrame")
        frame.setStyleSheet(
            "#calendarFrame {"
            " border: 1px solid #1F2937; border-radius: 3px; background-color: #111827;"
            " }"
        )
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(FRAME_MARGIN, FRAME_MARGIN, FRAME_MARGIN, FRAME_MARGIN)
        frame_layout.addWidget(self._calendar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*CONTENT_MARGINS)
        layout.addWidget(frame)

        self._on_page_changed(self._calendar.yearShown(), self._calendar.monthShown())

    def _style_weekend_colors(self) -> None:
        weekend_format = QTextCharFormat()
        weekend_format.setForeground(QColor(WEEKEND_COLOR))
        self._calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend_format)
        self._calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend_format)

    def _hide_month_arrows(self) -> None:
        # La navegacion de mes sigue disponible via el selector de mes/anio
        # de la barra superior -- estos botones de flecha quedan redundantes
        # (y uno de ellos ni siquiera se distingue sobre el fondo oscuro).
        for name in ("qt_calendar_prevmonth", "qt_calendar_nextmonth"):
            button = self._calendar.findChild(QToolButton, name)
            if button is not None:
                button.setVisible(False)

    def _on_page_changed(self, year: int, month: int) -> None:
        """Recalcula, por posicion de celda (fila, columna): cuales no
        pertenecen al mes mostrado (para opacarlas) y que fecha real le
        corresponde a cada una (para _DateCellDelegate: dias con
        grabacion). Tambien pide los dias con grabacion de este mes."""
        month_start = QDate(year, month, 1)
        first_day_of_week = self._calendar.firstDayOfWeek()
        leading_days = (month_start.dayOfWeek() - first_day_of_week.value + 7) % 7
        grid_start = month_start.addDays(-leading_days)

        # +1 en la fila: la fila 0 de la tabla interna es el encabezado de
        # dias de la semana (dom/lun/.../sab), las fechas empiezan en la 1.
        other_month_cells = set()
        cell_dates: dict[tuple[int, int], date] = {}
        for offset in range(GRID_WEEKS * 7):
            current = grid_start.addDays(offset)
            cell = (offset // 7 + 1, offset % 7)
            cell_dates[cell] = current.toPython()
            if current.year() != year or current.month() != month:
                other_month_cells.add(cell)

        self._other_month_cells = other_month_cells
        self._cell_dates = cell_dates
        self._repaint_table()
        self.month_changed.emit(year, month)

    def _repaint_table(self) -> None:
        table_view = self._calendar.findChild(QTableView, "qt_calendar_calendarview")
        if table_view is not None:
            table_view.viewport().update()

    def current_page(self) -> tuple[int, int]:
        return self._calendar.yearShown(), self._calendar.monthShown()

    def set_recorded_days(self, year: int, month: int, days: set[date]) -> None:
        # Descarta respuestas tardias de un mes que ya no se esta mostrando
        # (el usuario pudo haber navegado a otro mes mientras la consulta al
        # DVR seguia en curso).
        if (year, month) != self.current_page():
            return
        self._recorded_days = days
        self._repaint_table()

    def _on_selected(self, qdate) -> None:
        self.day_selected.emit(qdate.toPython())

    def selected_date(self) -> date:
        return self._calendar.selectedDate().toPython()

    def select_date(self, day: date) -> None:
        """Selecciona un dia por codigo (no por clic del usuario): a
        diferencia de un clic, NO emite day_selected -- MainWindow lo usa
        para sincronizar el calendario con la vista en vivo, y eso no debe
        interpretarse como "el usuario eligio otro dia". Tambien refresca el
        tope de fechas: setMaximumDate se fijo al construir y una app que
        sigue abierta pasada la medianoche no dejaria elegir el dia nuevo."""
        self._calendar.setMaximumDate(date.today())
        self._calendar.setSelectedDate(QDate(day.year, day.month, day.day))
