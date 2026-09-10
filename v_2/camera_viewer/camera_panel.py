from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QLabel

from .zoom_canvas import ZoomPanGraphicsView


class CameraPanel(ZoomPanGraphicsView):
    """Un panel de camara: muestra frames BGR (numpy, como los entrega
    OpenCV) con zoom/pan de la rueda del mouse (arrastre habilitado, ya que
    aqui no compite con ninguna otra accion de clic), y avisa con un doble
    clic para que el contenedor (CameraGrid) decida expandir/contraer."""

    double_clicked = Signal()

    def __init__(self, channel: int, parent=None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self._status_label = QLabel("Sin reproduccion", self)
        self._status_label.setStyleSheet(
            "background-color: rgba(15, 23, 42, 170); color: #E5E7EB;"
            " padding: 2px 6px; border-radius: 3px; font-weight: bold;"
        )
        self._status_label.move(6, 6)
        self._status_label.adjustSize()

    def _update_transform(self) -> None:
        # Zoom minimo (1.0) = la imagen completa cabe en el panel (como un
        # visor de fotos); zoom > 1.0 amplia desde ahi. Uniforme en x/y
        # para no distorsionar la imagen.
        self.resetTransform()
        scale = self._fit_scale() * self._zoom
        self.scale(scale, scale)

    def _fit_scale(self) -> float:
        if self._pixmap_item is None:
            return 1.0
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
            return 1.0
        viewport = self.viewport()
        return min(viewport.width() / pixmap.width(), viewport.height() / pixmap.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_transform()

    def set_frame(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888).copy()
        pixmap = QPixmap.fromImage(image)

        if self._pixmap_item is None:
            self._pixmap_item = self.scene().addPixmap(pixmap)
            self.scene().setSceneRect(0, 0, width, height)
            self.reset_zoom()
        else:
            self._pixmap_item.setPixmap(pixmap)

    def clear_frame(self) -> None:
        if self._pixmap_item is not None:
            self.scene().removeItem(self._pixmap_item)
            self._pixmap_item = None
        self.reset_zoom()

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.adjustSize()
        self._status_label.raise_()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
