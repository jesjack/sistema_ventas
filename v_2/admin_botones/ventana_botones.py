"""La ventana principal: matriz de botones (columnas) x usuarios (filas), con una casilla por
celda para la visibilidad de ese botón para ese usuario.

Reemplaza el intento de hacer esto con un diálogo UNO (ui/panel_admin.py, ver
admin_botones/__init__.py) -- aquí el encabezado sí puede rotar el texto (EncabezadoVertical, en
vertical puro), el arrastre para reordenar es un arrastre real de la columna completa (ver
TablaBotones -- no el `QHeaderView.setSectionsMovable` nativo, que solo muestra un fantasma
estático) y el doble clic también, sin ninguno de los rodeos que exigía UNO."""

from __future__ import annotations

import time

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from services.identidad import USUARIO_PLANTILLA

_ETIQUETA_PLANTILLA = "DEFAULT"

ANGULO_ENCABEZADO = 90  # grados; completamente vertical (pedido explícito, ya no diagonal)
ANCHO_COL_BOTON = 34
ALTO_ENCABEZADO_MINIMO = 60
ALTO_FILA = 26
ANCHO_COL_USUARIO = 160
MARGEN_REDIMENSION = 5  # px junto al borde de la sección reservados para redimensionar, no arrastrar
MIME_COLUMNA = "application/x-admin-botones-columna"

FILA_ACTIVO = 0  # fila fija (no se mueve, no es un boton_id) con la casilla activo/inactivo


def _etiqueta_usuario(nombre_usuario):
    return _ETIQUETA_PLANTILLA if nombre_usuario == USUARIO_PLANTILLA else nombre_usuario


def listar_usuarios_candidatos(usuarios_service):
    """Porte a Python puro (sin UNO) de ui/panel_admin.py:_listar_usuarios_candidatos:
    __default__ (la plantilla) siempre primero y con etiqueta amigable; el resto, usuarios
    reales vistos alguna vez en usuarios_sistema, en orden alfabético."""
    nombres = sorted(
        {str(nombre_usuario).strip().lower() for _id, nombre_usuario, *_resto in usuarios_service.listar_usuarios_sistema()}
    )
    nombres = [n for n in nombres if n != USUARIO_PLANTILLA]
    return [USUARIO_PLANTILLA] + nombres


def _crear_contenedor_casilla(marcada, habilitada, al_cambiar):
    """Una QCheckBox centrada de verdad dentro de su celda -- a diferencia de
    QTableWidgetItem + Qt.ItemIsUserCheckable, cuyo indicador de casilla el estilo lo posiciona
    con un margen fijo (no queda realmente centrado, por más que se use
    setTextAlignment(AlignCenter): eso alinea el texto del ítem, no el indicador). Con un widget
    propio por celda (QCheckBox dentro de un QHBoxLayout con AlignCenter y márgenes en cero) el
    centrado es exacto.

    `al_cambiar(marcada: bool)` se conecta DESPUÉS de fijar el estado inicial, para que
    reconstruir() nunca dispare el guardado como si el usuario la hubiera tocado."""
    casilla = QCheckBox()
    casilla.setChecked(marcada)
    casilla.setEnabled(habilitada)
    casilla.toggled.connect(al_cambiar)

    contenedor = QWidget()
    layout = QHBoxLayout(contenedor)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(casilla)
    return contenedor


def _alto_necesario_encabezado(etiquetas, metricas_fuente):
    """Con texto vertical puro (90°) el encabezado necesita tanta altura como ancho tenga el
    texto MÁS LARGO -- al rotarlo, ese ancho se vuelve alto. A diferencia de la versión en
    diagonal, aquí no hace falta ningún margen extra a la derecha para la última columna: un
    texto rotado 90° sube derecho desde su columna, sin desviarse lateralmente."""
    if not etiquetas:
        return ALTO_ENCABEZADO_MINIMO
    ancho_max = max(metricas_fuente.horizontalAdvance(str(e)) for e in etiquetas)
    return max(ALTO_ENCABEZADO_MINIMO, ancho_max + 16)


class EncabezadoVertical(QHeaderView):
    """Encabezado horizontal que pinta el texto de cada columna en vertical puro (90°, técnica
    estándar de Qt) y que arrastra la columna COMPLETA (encabezado + celdas) al reordenar.

    Solo se sobreescribe paintSection, nunca paintEvent completo: QHeaderView pinta en realidad
    sobre su propio viewport interno (hereda de QAbstractScrollArea, confirmado con
    `hasattr(header, "viewport")`), no sobre `self` -- se intentó un paintEvent propio con
    `QPainter(self)` y en un X real (no solo en la prueba offscreen) tiraba
    "QWidget::paintEngine: Should no longer be called" / "Paint device returned engine == 0" en
    CADA fotograma, dejando el encabezado en blanco. Dejando que QHeaderView arme su propio
    QPainter (el que YA sabemos que funciona) y solo interviniendo en paintSection se evita eso.

    Eso sí deja el problema de que paintSection por defecto rellena el fondo de CADA sección al
    pintarla; se resuelve pintando el fondo de TODO el encabezado una sola vez, en la primera
    sección que le toque pintar en cada ciclo (ver _fondo_pintado), en vez de una vez por sección.

    El arrastre NO usa QHeaderView.setSectionsMovable: se confirmó en vivo (arrastre real
    simulado con Xvfb + xdotool, con capturas de pantalla) que ese mecanismo nativo solo muestra
    un rectángulo fantasma ESTÁTICO sobre el encabezado mientras el cuerpo (las casillas) se
    queda completamente congelado hasta soltar el mouse -- ni siquiera las demás etiquetas del
    encabezado se mueven en vivo. Además, nuestro propio manejo de esa señal (`sectionMoved`,
    reconstruyendo toda la tabla) chocaba con la propia limpieza interna de Qt del rectángulo
    fantasma, dejando un resto gris pegado en pantalla.

    En su lugar se adapta la técnica de ~/ejemplos/qt-dnd/tabla_columnas.py (compartida por otra
    sesión): un QDrag con una imagen real de la columna completa (capturada con `grab()`,
    semitransparente) que sigue al cursor de verdad, moviendo con `moveSection()` -- solo el
    orden VISUAL, no los datos -- a las demás columnas EN VIVO mientras se arrastra. Ver
    TablaBotones para la mitad de esta lógica que vive del lado de la tabla (el origen y destino
    del arrastre).

    Como interceptamos mousePress/Move/Release por completo para nuestro propio arrastre, Qt deja
    de ver la secuencia de clics para su propia detección de doble clic
    (QHeaderView.sectionDoubleClicked ya no se dispara) -- se reimplementa a mano comparando el
    tiempo entre dos sueltas sobre la misma sección contra QApplication.doubleClickInterval()."""

    dobleClicEncabezado = Signal(int)  # logicalIndex

    def __init__(self, tabla):
        super().__init__(Qt.Orientation.Horizontal, tabla)
        self.tabla = tabla
        self.setSectionsClickable(True)
        self._fondo_pintado = False
        self._alto = ALTO_ENCABEZADO_MINIMO
        self.setFixedHeight(self._alto)

        self._press_pos = None
        self._logico_presionado = None
        self._ultimo_logico_soltado = None
        self._ultimo_release_ts = 0.0

    def establecer_alto(self, alto):
        if alto != self._alto:
            self._alto = alto
            self.setFixedHeight(alto)
            self.updateGeometry()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(self._alto)
        return hint

    def paintEvent(self, event):
        self._fondo_pintado = False
        super().paintEvent(event)

    def paintSection(self, painter, rect, logicalIndex):
        if not self._fondo_pintado:
            painter.fillRect(self.rect(), self.palette().window())
            self._fondo_pintado = True

        texto = self.model().headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole)
        if not texto:
            return

        x = rect.left() + rect.width() / 2
        y = self.height() - 6  # el pivote es la parte de ABAJO del texto -- coincide con la columna

        painter.save()
        painter.translate(x, y)
        painter.rotate(-ANGULO_ENCABEZADO)
        # Punto, no rect+alineación: dibujar en un rect grande con AlignVCenter desplazaba el
        # inicio del texto lejos del pivote, que es justo lo que hacía que el texto NO coincidiera
        # con su columna. Con un punto, el primer carácter nace exactamente en el pivote (más un
        # pequeño margen), y con 90° crece derecho hacia arriba sin ningún desvío lateral.
        painter.drawText(QPointF(4, 0), str(texto))
        painter.restore()

    # ---- detección de qué sección hay bajo el cursor (ni en el borde de redimensionar) ----

    def _seccion_en(self, x):
        logico = self.logicalIndexAt(x)
        if logico == -1:
            return -1
        izq = self.sectionViewportPosition(logico)
        der = izq + self.sectionSize(logico)
        if izq + MARGEN_REDIMENSION < x < der - MARGEN_REDIMENSION:
            return logico
        return -1

    # ---- arrastre propio (reemplaza sectionsMovable) + doble clic reimplementado a mano ----

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        logico = self._seccion_en(pos.x()) if e.button() == Qt.MouseButton.LeftButton else -1
        if logico == -1:
            super().mousePressEvent(e)  # redimensionar, etc.
            return
        self._press_pos = pos
        self._logico_presionado = logico

    def mouseMoveEvent(self, e):
        if self._press_pos is not None and e.buttons() & Qt.MouseButton.LeftButton:
            if (e.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                logico, pos = self._logico_presionado, self._press_pos
                self._press_pos = None
                self._logico_presionado = None
                self.tabla.arrastrar_columna(logico, pos)
            return
        if self._press_pos is None:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press_pos is None:
            super().mouseReleaseEvent(e)
            return

        logico = self._logico_presionado
        self._press_pos = None
        self._logico_presionado = None

        ahora = time.monotonic()
        es_doble = (
            logico == self._ultimo_logico_soltado
            and (ahora - self._ultimo_release_ts) <= QApplication.doubleClickInterval() / 1000
        )
        if es_doble:
            self._ultimo_logico_soltado = None
            self.dobleClicEncabezado.emit(logico)
        else:
            self._ultimo_logico_soltado = logico
            self._ultimo_release_ts = ahora

    # La cabecera también es zona de drop (se puede soltar sobre otro encabezado): reenviamos a
    # la tabla, que es quien conoce el estado del arrastre (_arrastrada).
    def dragEnterEvent(self, e):
        self.tabla.dragEnterEvent(e)

    def dragMoveEvent(self, e):
        self.tabla.dragMoveEvent(e)

    def dropEvent(self, e):
        self.tabla.dropEvent(e)


class TablaBotones(QTableWidget):
    """QTableWidget con arrastre real de columnas completas (encabezado + celdas), adaptado de
    ~/ejemplos/qt-dnd/tabla_columnas.py. `moveSection()` reordena solo lo VISUAL en vivo mientras
    se arrastra (los datos/índices lógicos no cambian); recién al soltar (dropEvent) se llama a
    `al_soltar_columna(orden_logico)` -- la lista de ÍNDICES LÓGICOS en el nuevo orden
    izquierda-a-derecha -- para que quien la use (VentanaBotones) persista el nuevo `orden` una
    sola vez, sin reconstruir nada (la pantalla ya quedó exactamente como debe)."""

    def __init__(self, al_soltar_columna):
        super().__init__()
        self._al_soltar_columna = al_soltar_columna
        self.setAcceptDrops(True)
        self._arrastrada = None

    # ------------------------------------------------ origen del arrastre
    def arrastrar_columna(self, logico, pos_en_cabecera: QPoint):
        h = self.horizontalHeader()
        self._arrastrada = logico
        visual_original = h.visualIndex(logico)

        # Imagen: la columna entera (encabezado + celdas visibles), semitransparente -- por esto
        # se siente como un arrastre real de la columna, no una copia solo del encabezado.
        x = h.sectionViewportPosition(logico)
        ancho = h.sectionSize(logico)
        esquina = h.viewport().mapTo(self, QPoint(x, 0))
        alto = h.height() + self.viewport().height()
        captura = self.grab(QRect(esquina.x(), esquina.y(), ancho, alto))
        pix = QPixmap(captura.size())
        pix.setDevicePixelRatio(captura.devicePixelRatio())
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setOpacity(0.75)
        p.drawPixmap(0, 0, captura)
        p.end()

        mime = QMimeData()
        mime.setData(MIME_COLUMNA, QByteArray(str(logico).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(pos_en_cabecera.x() - x, pos_en_cabecera.y()))

        resultado = drag.exec(Qt.DropAction.MoveAction)
        if resultado == Qt.DropAction.IgnoreAction:
            # Cancelado (Esc, o soltado fuera): Qt ya lo maneja solo, solo falta volver al orden
            # inicial -- nunca se llegó a persistir nada porque dropEvent no corrió.
            h.moveSection(h.visualIndex(logico), visual_original)
        self._arrastrada = None

    # ------------------------------------------------ reacomodo en vivo
    def reordenar_hacia(self, x):
        """Mueve la columna arrastrada según la posición x (coords de viewport).

        Evita parpadeo con columnas de distinto ancho: solo ocupa la posición destino si, tras
        moverla, el cursor quedaría encima de la columna arrastrada; si no, se queda una posición
        antes."""
        h = self.horizontalHeader()
        actual = h.visualIndex(self._arrastrada)
        destino = h.visualIndexAt(x)
        if destino == -1 or destino == actual:
            return
        ancho = h.sectionSize(self._arrastrada)
        ld = h.logicalIndex(destino)
        izq = h.sectionViewportPosition(ld)
        der = izq + h.sectionSize(ld)
        if destino > actual and x < der - ancho:
            destino -= 1
        elif destino < actual and x >= izq + ancho:
            destino += 1
        if destino != actual:
            h.moveSection(actual, destino)

    # ------------------------------------------------ destino del arrastre
    def _es_nuestro(self, e):
        return e.mimeData().hasFormat(MIME_COLUMNA) and self._arrastrada is not None

    def dragEnterEvent(self, e):
        if self._es_nuestro(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not self._es_nuestro(e):
            e.ignore()
            return
        self.reordenar_hacia(e.position().toPoint().x())
        e.acceptProposedAction()

    def dropEvent(self, e):
        if not self._es_nuestro(e):
            e.ignore()
            return
        e.acceptProposedAction()
        h = self.horizontalHeader()
        orden_logico = [h.logicalIndex(v) for v in range(h.count())]
        self._al_soltar_columna(orden_logico)


class DialogoBoton(QDialog):
    """Crear/editar un botón: etiqueta y archivo en acciones/ (sin .py). Sin campo de orden --
    se reordena arrastrando la columna, nunca escribiendo un número a mano (mismo criterio que
    ya tenía la versión UNO con las flechas)."""

    def __init__(self, parent=None, etiqueta_inicial="", archivo_inicial=""):
        super().__init__(parent)
        self.setWindowTitle("Editar botón" if etiqueta_inicial or archivo_inicial else "Nuevo botón")

        self.campo_etiqueta = QLineEdit(etiqueta_inicial)
        self.campo_archivo = QLineEdit(archivo_inicial)

        formulario = QFormLayout()
        formulario.addRow("Etiqueta (texto del botón):", self.campo_etiqueta)
        formulario.addRow("Archivo en acciones/ (sin .py):", self.campo_archivo)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(formulario)
        layout.addWidget(botones)

    def datos(self):
        etiqueta = self.campo_etiqueta.text().strip()
        archivo = self.campo_archivo.text().strip()
        if not etiqueta or not archivo:
            return None
        return etiqueta, archivo


class VentanaBotones(QMainWindow):
    # Se emite desde el hilo que escucha el socket de instancia única (ver
    # admin_botones/instancia_unica.py y __main__.py) -- nunca se toca la UI directo desde ese
    # hilo; conectar una señal Qt y emitirla es la forma segura de cruzar de hilo a hilo.
    solicitar_traer_al_frente = Signal()

    def __init__(self, botones_service, usuarios_service):
        super().__init__()
        self.botones_service = botones_service
        self.usuarios_service = usuarios_service
        self.setWindowTitle("Administrar botones")
        self.solicitar_traer_al_frente.connect(self._traer_al_frente)

        self.tabla = TablaBotones(self._al_soltar_columna_arrastrada)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setFrameShape(QFrame.Shape.NoFrame)
        self.tabla.setShowGrid(False)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabla.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabla.verticalHeader().setDefaultSectionSize(ALTO_FILA)

        encabezado = EncabezadoVertical(self.tabla)
        self.tabla.setHorizontalHeader(encabezado)
        encabezado.dobleClicEncabezado.connect(self._al_doble_clic_encabezado)

        boton_crear = QPushButton("Crear botón")
        boton_crear.clicked.connect(self._al_crear)

        barra = QHBoxLayout()
        barra.addWidget(boton_crear)
        barra.addStretch(1)

        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        # La tabla primero, la barra de opciones extra (Crear botón...) al final -- pedido
        # explícitamente en vez de dejarla arriba.
        layout.addWidget(self.tabla)
        layout.addLayout(barra)
        self.setCentralWidget(contenedor)

        self._botones = []
        self._usuarios_filas = []
        self.reconstruir()

    # ---- construcción de la matriz ----

    def reconstruir(self):
        self._botones = self.botones_service.listar_botones()
        candidatos = listar_usuarios_candidatos(self.usuarios_service)
        visibilidad_por_boton = {
            boton[0]: set(self.botones_service.listar_visibilidad(boton[0])) for boton in self._botones
        }
        extra = sorted({u for visibles in visibilidad_por_boton.values() for u in visibles if u not in candidatos})
        self._usuarios_filas = candidatos + extra
        self._visibilidad_por_boton = visibilidad_por_boton

        # setRowCount(0)/setColumnCount(0) primero: QTableWidget.clear() NO borra los widgets
        # puestos con setCellWidget() (a diferencia de los QTableWidgetItem, que sí limpia) --
        # sin este paso, los checkbox de la corrida anterior quedarían flotando huérfanos por
        # detrás de los nuevos.
        self.tabla.setRowCount(0)
        self.tabla.setColumnCount(0)
        self.tabla.setColumnCount(len(self._botones))
        self.tabla.setRowCount(1 + len(self._usuarios_filas))  # fila 0 = activo/inactivo

        self.tabla.setHorizontalHeaderLabels([boton[2] for boton in self._botones])
        for i in range(len(self._botones)):
            self.tabla.setColumnWidth(i, ANCHO_COL_BOTON)

        encabezado = self.tabla.horizontalHeader()
        encabezado.establecer_alto(_alto_necesario_encabezado([b[2] for b in self._botones], encabezado.fontMetrics()))

        for i, boton in enumerate(self._botones):
            boton_id, _ni, _etiqueta, _archivo, _orden, activo = boton

            def al_cambiar_activo(marcada, boton_id=boton_id):
                self.botones_service.establecer_activo(boton_id, marcada)
                self.reconstruir()

            self.tabla.setCellWidget(
                FILA_ACTIVO, i, _crear_contenedor_casilla(bool(activo), True, al_cambiar_activo)
            )

            visibles = visibilidad_por_boton[boton_id]
            for j, nombre_usuario in enumerate(self._usuarios_filas):
                fila = 1 + j

                def al_cambiar_visibilidad(marcada, boton_id=boton_id, nombre_usuario=nombre_usuario):
                    visibles_actuales = self._visibilidad_por_boton.setdefault(boton_id, set())
                    if marcada:
                        visibles_actuales.add(nombre_usuario)
                    else:
                        visibles_actuales.discard(nombre_usuario)
                    self.botones_service.set_visibilidad(boton_id, sorted(visibles_actuales))

                self.tabla.setCellWidget(
                    fila, i,
                    _crear_contenedor_casilla(nombre_usuario in visibles, bool(activo), al_cambiar_visibilidad),
                )

        etiquetas_filas = ["Activo"] + [_etiqueta_usuario(u) for u in self._usuarios_filas]
        self.tabla.setVerticalHeaderLabels(etiquetas_filas)
        self.tabla.verticalHeader().setFixedWidth(ANCHO_COL_USUARIO)

        self._ajustar_tamano()

    def _ajustar_tamano(self):
        # Sin esto, la ventana se queda con el tamaño de la última vez que tuvo más columnas/filas
        # (o el inicial), dejando una franja en blanco a la derecha y abajo de la tabla real.
        ancho_tabla = self.tabla.verticalHeader().width()
        ancho_tabla += sum(self.tabla.columnWidth(i) for i in range(self.tabla.columnCount()))
        alto_tabla = self.tabla.horizontalHeader().height()
        alto_tabla += sum(self.tabla.rowHeight(i) for i in range(self.tabla.rowCount()))

        self.tabla.setFixedSize(ancho_tabla + 2, alto_tabla + 2)
        self.centralWidget().adjustSize()
        self.adjustSize()

    # ---- interacción ----

    def _traer_al_frente(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _al_soltar_columna_arrastrada(self, orden_logico):
        # El arrastre (ver TablaBotones/EncabezadoVertical) ya dejó la pantalla exactamente como
        # debe quedar -- solo falta guardar el orden nuevo, una sola vez. self._botones sigue
        # siendo válido para mapear índice lógico -> boton_id: arrastrar solo cambia el orden
        # VISUAL de las columnas, nunca sus índices lógicos.
        for nueva_posicion, logico in enumerate(orden_logico):
            boton_id = self._botones[logico][0]
            self.botones_service.editar_boton(boton_id, orden=nueva_posicion)

    def _al_doble_clic_encabezado(self, logical_index: int):
        boton_id, _ni, etiqueta, archivo, _orden, _activo = self._botones[logical_index]
        respuesta = QMessageBox.question(
            self,
            etiqueta,
            f"¿Qué deseas hacer con '{etiqueta}'?\n\nSí = Editar, No = Eliminar",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if respuesta == QMessageBox.StandardButton.Yes:
            dialogo = DialogoBoton(self, etiqueta, archivo)
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                datos = dialogo.datos()
                if datos is not None:
                    nueva_etiqueta, nuevo_archivo = datos
                    self.botones_service.editar_boton(boton_id, etiqueta=nueva_etiqueta, archivo_accion=nuevo_archivo)
                    self.reconstruir()
        elif respuesta == QMessageBox.StandardButton.No:
            self.botones_service.eliminar_boton(boton_id)
            self.reconstruir()

    def _al_crear(self):
        dialogo = DialogoBoton(self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            datos = dialogo.datos()
            if datos is not None:
                etiqueta, archivo = datos
                try:
                    self.botones_service.crear_boton(archivo, etiqueta, archivo, orden=len(self._botones))
                except ValueError as exc:
                    QMessageBox.warning(self, "No se pudo crear", str(exc))
                self.reconstruir()
