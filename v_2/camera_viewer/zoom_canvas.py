from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
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

    # Un scroll rapido y sostenido (el disparador identificado del freeze de
    # camera_viewer, ver investigacion de 2026-09-17) puede mandar cientos de
    # QWheelEvent en pocos segundos -- recalcular la transformacion y forzar
    # un repintado en CADA uno por separado le agrega al hilo de la GUI mucho
    # mas trabajo del necesario para lo que el ojo puede distinguir. En vez
    # de eso, se acumulan los deltas que lleguen dentro de esta ventana y se
    # aplican de una sola vez (~60Hz, ya es mas fluido de lo perceptible).
    ZOOM_THROTTLE_MS = 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._zoom = 1.0
        self._pending_zoom_factor = 1.0

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._zoom_apply_timer = QTimer(self)
        self._zoom_apply_timer.setSingleShot(True)
        self._zoom_apply_timer.timeout.connect(self._apply_pending_zoom)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return

        factor = self.ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self.ZOOM_STEP
        self._pending_zoom_factor *= factor
        if not self._zoom_apply_timer.isActive():
            self._zoom_apply_timer.start(self.ZOOM_THROTTLE_MS)
        event.accept()

    def _apply_pending_zoom(self) -> None:
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * self._pending_zoom_factor))
        self._pending_zoom_factor = 1.0
        if new_zoom != self._zoom:
            self._zoom = new_zoom
            self._update_transform()
            self.zoom_changed.emit(self._zoom)

    def _update_transform(self) -> None:
        """Recalcula la transformacion desde cero a partir de self._zoom
        (no incremental, para no arrastrar error de punto flotante tras
        muchos pasos). Por defecto: escala uniforme x/y (para imagenes,
        evita distorsion). TimelineWidget la sobreescribe para combinarla
        con un factor de ajuste al ancho del panel."""
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def reset_zoom(self) -> None:
        # Descarta cualquier zoom acumulado aun pendiente de aplicar (ver
        # ZOOM_THROTTLE_MS) -- si no, ese remanente se aplicaria despues
        # sobre el zoom recien reseteado, dando un salto inesperado.
        self._zoom_apply_timer.stop()
        self._pending_zoom_factor = 1.0
        self._zoom = self.MIN_ZOOM
        self._update_transform()
        self.zoom_changed.emit(self._zoom)

    @property
    def zoom(self) -> float:
        return self._zoom
