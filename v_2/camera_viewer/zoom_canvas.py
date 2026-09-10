from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


class ZoomPanGraphicsView(QGraphicsView):
    """Canvas base con zoom centrado en el cursor (rueda del mouse) y
    scrollbars para recorrer el contenido cuando no cabe en la vista. Es el
    componente que comparten la linea de tiempo y cada panel de camara --
    cualquier mejora al zoom/pan aplica a los cinco lugares por igual.

    Subclases pueden sobreescribir _apply_zoom() si necesitan zoom en un
    solo eje (ver TimelineWidget, que solo zoomea horizontalmente)."""

    zoom_changed = Signal(float)

    MIN_ZOOM = 1.0
    MAX_ZOOM = 40.0
    ZOOM_STEP = 1.15

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._zoom = 1.0

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return

        factor = self.ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self.ZOOM_STEP
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * factor))
        if new_zoom != self._zoom:
            self._zoom = new_zoom
            self._update_transform()
            self.zoom_changed.emit(self._zoom)
        event.accept()

    def _update_transform(self) -> None:
        """Recalcula la transformacion desde cero a partir de self._zoom
        (no incremental, para no arrastrar error de punto flotante tras
        muchos pasos). Por defecto: escala uniforme x/y (para imagenes,
        evita distorsion). TimelineWidget la sobreescribe para combinarla
        con un factor de ajuste al ancho del panel."""
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def reset_zoom(self) -> None:
        self._zoom = self.MIN_ZOOM
        self._update_transform()
        self.zoom_changed.emit(self._zoom)

    @property
    def zoom(self) -> float:
        return self._zoom
