from __future__ import annotations

import re

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QLabel

from .zoom_canvas import ZoomPanGraphicsView


class CameraPanel(ZoomPanGraphicsView):
    """Un panel de camara: muestra frames BGR (numpy, como los entrega
    OpenCV) con zoom/pan de la rueda del mouse (arrastre habilitado, ya que
    aqui no compite con ninguna otra accion de clic), y avisa con un doble
    clic para que el contenedor (CameraGrid) decida expandir/contraer."""

    double_clicked = Signal()

    # El label de estado va al centro del panel cuando el mensaje requiere
    # atencion (sin video que mostrar, conectando, descargando, reintentos,
    # errores, o la invitacion a elegir una hora); se queda en la esquina
    # solo durante reproduccion normal, para no taparle el frame al
    # usuario: la velocidad de reproduccion ("x1", "x2"...) o "En vivo".
    SPEED_STATUS_PATTERN = re.compile(r"x\d+(\.\d+)?")
    LIVE_STATUS_PREFIX = "En vivo"
    CORNER_MARGIN = 6

    LABEL_STYLE = (
        "background-color: rgba(15, 23, 42, 170); color: #E5E7EB;"
        " padding: 2px 6px; border-radius: 3px; font-weight: bold;"
    )
    # "En vivo" en rojo con letras blancas, como el indicador clasico de
    # transmision en directo -- se distingue de un vistazo de la
    # reproduccion de grabaciones.
    LIVE_LABEL_STYLE = (
        "background-color: #DC2626; color: #FFFFFF;"
        " padding: 2px 6px; border-radius: 3px; font-weight: bold;"
    )

    # Cuanto esperar sin recibir un nuevo evento de zoom antes de reactivar
    # el filtrado suave (ver wheelEvent) -- bastante corto para que se sienta
    # inmediato al soltar la rueda, pero suficiente para no reactivarlo entre
    # ticks sueltos de un scroll rapido.
    ZOOM_SMOOTH_IDLE_MS = 150

    def __init__(self, channel: int, initial_status: str = "Sin reproducción", parent=None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self._pixmap_item: QGraphicsPixmapItem | None = None

        # A diferencia del timeline (que comparte esta misma base, ver
        # zoom_canvas.ZoomPanGraphicsView), la escena de un panel de camara
        # nunca dibuja nada vectorial -- solo un unico QGraphicsPixmapItem
        # con el frame de video. Antialiasing suaviza bordes de formas
        # dibujadas con QPainter, asi que aqui no aporta nada visible; se
        # desactiva para no pagar su costo de render en cada frame/zoom.
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # ScrollBarAsNeeded (heredado de la base) crea un ciclo real con
        # _update_transform(): esta calcula la escala a partir del tamaño
        # ACTUAL del viewport, asi que mostrar/ocultar una scrollbar cambia
        # el viewport -> dispara resizeEvent -> recalcula la escala -> puede
        # volver a cambiar si la scrollbar hace falta o no -> vuelve a
        # disparar resizeEvent. Confirmado como causa real del freeze bajo
        # zoom agresivo: un volcado de pila durante un congelamiento real
        # (investigacion 2026-09-17) atrapo al hilo de la GUI exactamente
        # dentro de resizeEvent -> _update_transform mientras el usuario NO
        # estaba redimensionando la ventana. El paneo ya funciona por
        # arrastre (ScrollHandDrag, ver arriba), igual que el timeline (que
        # tampoco usa la scrollbar real, ver timeline_widget), asi que
        # quitarla no le resta nada al usuario.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._zoom_smooth_idle_timer = QTimer(self)
        self._zoom_smooth_idle_timer.setSingleShot(True)
        self._zoom_smooth_idle_timer.timeout.connect(self._restore_smooth_pixmap_transform)

        self._status_label = QLabel(initial_status, self)
        self._status_label.setStyleSheet(self.LABEL_STYLE)
        self._status_is_live = False
        self._status_label.adjustSize()
        self._reposition_status_label()

    def _update_transform(self) -> None:
        # Zoom minimo (1.0) = la imagen estirada llena el panel entero (por
        # ancho Y alto, cada eje por separado) en vez de mantener su
        # proporcion original y dejar franjas vacias -- a proposito: no
        # todas las camaras entregan la misma proporcion (una de otra
        # marca en produccion llega mas angosta que las demas), y el orden
        # de reconexion de los 4 canales no esta garantizado, asi que
        # cualquier panel podria tocarle la camara "rara" en cualquier
        # momento. zoom > 1.0 amplia mas alla desde ahi, ya de forma
        # uniforme.
        self.resetTransform()
        scale_x, scale_y = self._fit_scale()
        self.scale(scale_x * self._zoom, scale_y * self._zoom)

    def _fit_scale(self) -> tuple[float, float]:
        if self._pixmap_item is None:
            return 1.0, 1.0
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
            return 1.0, 1.0
        viewport = self.viewport()
        return viewport.width() / pixmap.width(), viewport.height() / pixmap.height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_transform()
        self._reposition_status_label()

    def showEvent(self, event) -> None:
        # Necesario para paneles dentro de un QStackedWidget (ver
        # MainWindow: un CameraGrid para vivo y otro para grabaciones):
        # mientras un panel esta OCULTO (la otra pagina del stack activa)
        # puede recibir su primer frame igual, y _fit_scale() calcula
        # contra el tamaño del viewport en ese momento -- que para una
        # pagina oculta puede no estar bien asentado todavia. Sin esto, el
        # encaje calculado mientras estaba oculto se queda pegado para
        # siempre (resizeEvent no vuelve a dispararse solo por mostrarse,
        # si el tamaño no cambio). Recalcular aqui, justo cuando el panel
        # de verdad se hace visible, usa el tamaño ya correcto.
        super().showEvent(event)
        self._update_transform()
        self._reposition_status_label()

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
        # El modo en vivo lo llama por cada frame (~30/s por canal): sin
        # este corte, cada llamada repintaba el estilo y recalculaba el
        # tamaño de un label que no cambio.
        if text == self._status_label.text():
            return

        is_live = text.startswith(self.LIVE_STATUS_PREFIX)
        if is_live != self._status_is_live:
            self._status_is_live = is_live
            self._status_label.setStyleSheet(self.LIVE_LABEL_STYLE if is_live else self.LABEL_STYLE)

        self._status_label.setText(text)
        self._status_label.adjustSize()
        self._reposition_status_label()
        self._status_label.raise_()

    def _is_corner_status(self, text: str) -> bool:
        return text.startswith(self.LIVE_STATUS_PREFIX) or bool(self.SPEED_STATUS_PATTERN.fullmatch(text))

    def _reposition_status_label(self) -> None:
        if self._is_corner_status(self._status_label.text()):
            self._status_label.move(self.CORNER_MARGIN, self.CORNER_MARGIN)
            return

        x = (self.width() - self._status_label.width()) // 2
        y = (self.height() - self._status_label.height()) // 2
        self._status_label.move(max(0, x), max(0, y))

    def wheelEvent(self, event: QWheelEvent) -> None:
        # SmoothPixmapTransform (interpolacion bilineal del frame al
        # escalarlo) es lo que de verdad se nota visualmente en un panel de
        # camara, pero tambien lo que mas cuesta repintar -- medido: ~8x mas
        # lento que sin el (ver investigacion de 2026-09-17). Mientras el
        # usuario esta moviendo la rueda activamente se prioriza fluidez
        # (se apaga); en cuanto se detiene un rato corto (ZOOM_SMOOTH_IDLE_MS)
        # se reactiva para que el frame en reposo se vea nitido.
        if event.angleDelta().y() != 0:
            self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            self._zoom_smooth_idle_timer.start(self.ZOOM_SMOOTH_IDLE_MS)
        super().wheelEvent(event)

    def _restore_smooth_pixmap_transform(self) -> None:
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
