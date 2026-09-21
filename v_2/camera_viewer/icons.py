from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# Iconos de los botones de reproducción y de marcas, dibujados con QPainter: no dependen de
# fuentes ni del tema del sistema (los iconos "estándar" de Qt varían con el estilo y con
# Fusion pueden faltar). Cada icono trae sus tres tintas: normal, deshabilitado y "encendido"
# (botón marcado, p. ej. la reversa activa), en una cuadrícula de 24 x 24 (nítida a 2x).

ICON_SIZE = QSize(20, 20)
GRID = 24
SCALE = 2  # píxeles reales por unidad lógica

COLOR_NORMAL = QColor("#E5E7EB")
COLOR_DISABLED = QColor("#6B7280")
COLOR_ON = QColor("#FFFFFF")


def _pixmap(draw, color: QColor) -> QPixmap:
    pixmap = QPixmap(GRID * SCALE, GRID * SCALE)
    pixmap.setDevicePixelRatio(SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    draw(painter, color)
    painter.end()
    return pixmap


def _icon(draw) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pixmap(draw, COLOR_NORMAL), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_pixmap(draw, COLOR_ON), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(_pixmap(draw, COLOR_DISABLED), QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(_pixmap(draw, COLOR_DISABLED), QIcon.Mode.Disabled, QIcon.State.On)
    return icon


def _triangle(painter: QPainter, *points: tuple[float, float]) -> None:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    painter.drawPath(path)


def _draw_pause(painter: QPainter, _color: QColor) -> None:
    painter.drawRoundedRect(QRectF(6, 4, 4.5, 16), 1, 1)
    painter.drawRoundedRect(QRectF(13.5, 4, 4.5, 16), 1, 1)


def _draw_play(painter: QPainter, _color: QColor) -> None:
    _triangle(painter, (7, 4), (7, 20), (19.5, 12))


def _draw_reverse(painter: QPainter, _color: QColor) -> None:
    _triangle(painter, (12, 5), (12, 19), (2.5, 12))
    _triangle(painter, (21.5, 5), (21.5, 19), (12, 12))


def _draw_bracket(left: bool):
    def draw(painter: QPainter, color: QColor) -> None:
        pen = QPen(color, 3.2)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inner, outer = (16.0, 8.0) if left else (8.0, 16.0)
        path = QPainterPath(QPointF(inner, 5))
        path.lineTo(outer, 5)
        path.lineTo(outer, 19)
        path.lineTo(inner, 19)
        painter.drawPath(path)

    return draw


def pause_icon() -> QIcon:
    return _icon(_draw_pause)


def play_icon() -> QIcon:
    return _icon(_draw_play)


def reverse_icon() -> QIcon:
    return _icon(_draw_reverse)


def mark_start_icon() -> QIcon:
    """Corchete de apertura: "el clip empieza aquí"."""
    return _icon(_draw_bracket(left=True))


def mark_end_icon() -> QIcon:
    """Corchete de cierre: "el clip termina aquí"."""
    return _icon(_draw_bracket(left=False))
