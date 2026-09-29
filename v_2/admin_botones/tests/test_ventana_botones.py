"""Matriz de botones x usuarios (Qt/PySide6), sin GUI real. Correr desde v_2/:
.venv/bin/python -m unittest admin_botones.tests.test_ventana_botones -v"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QMessageBox  # noqa: E402

from services.botones_service import BotonesService  # noqa: E402
from services.usuarios_service import UsuariosService  # noqa: E402

from admin_botones.ventana_botones import (  # noqa: E402
    ALTO_ENCABEZADO_MINIMO,
    FILA_ACTIVO,
    DialogoBoton,
    TablaBotones,
    VentanaBotones,
    _alto_necesario_encabezado,
    _etiqueta_usuario,
    listar_usuarios_candidatos,
)
from services.identidad import USUARIO_PLANTILLA  # noqa: E402


def _clic(encabezado, logico):
    """Simula un clic simple (press + release) sobre el centro de esa sección del encabezado --
    con eventos QMouseEvent reales, no llamadas directas, para probar la detección de doble clic
    reimplementada a mano (ver EncabezadoVertical.mouseReleaseEvent)."""
    x = encabezado.sectionViewportPosition(logico) + encabezado.sectionSize(logico) // 2
    pos = QPointF(x, encabezado.height() // 2)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    encabezado.mousePressEvent(press)
    encabezado.mouseReleaseEvent(release)


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])


def _casilla(tabla, fila, columna):
    return tabla.cellWidget(fila, columna).findChild(QCheckBox)


class VentanaBotonesTests(QtTestCase):
    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name))
        self.db_path = tmp.name

        self.botones_service = BotonesService(self.db_path)
        self.usuarios_service = UsuariosService(self.db_path)

        self.usuario_a_id, _ = self.usuarios_service.asegurar_usuario_sistema(
            {"nombre_usuario": "ana", "sistema_operativo": "Linux", "version_sistema": "", "nombre_equipo": "pc1", "dominio": ""}
        )
        self.usuario_b_id, _ = self.usuarios_service.asegurar_usuario_sistema(
            {"nombre_usuario": "beto", "sistema_operativo": "Linux", "version_sistema": "", "nombre_equipo": "pc1", "dominio": ""}
        )

        self.boton1_id = self.botones_service.crear_boton("boton1", "Boton Uno", "boton1", orden=0)
        self.boton2_id = self.botones_service.crear_boton("boton2", "Boton Dos", "boton2", orden=1)
        self.botones_service.set_visibilidad(self.boton1_id, ["ana"])

        self.ventana = VentanaBotones(self.botones_service, self.usuarios_service)
        self.addCleanup(self.ventana.close)

    def test_matriz_refleja_visibilidad_inicial(self) -> None:
        self.assertEqual(self.ventana.tabla.columnCount(), 2)
        # fila 0 = activo/inactivo, filas siguientes = __default__, ana, beto (alfabético)
        etiquetas_filas = [self.ventana.tabla.verticalHeaderItem(f).text() for f in range(self.ventana.tabla.rowCount())]
        self.assertEqual(etiquetas_filas[0], "Activo")
        self.assertIn("ana", etiquetas_filas)

        fila_ana = etiquetas_filas.index("ana")
        self.assertTrue(_casilla(self.ventana.tabla, fila_ana, 0).isChecked())
        self.assertFalse(_casilla(self.ventana.tabla, fila_ana, 1).isChecked())

    def test_marcar_casilla_de_visibilidad_persiste(self) -> None:
        etiquetas_filas = [self.ventana.tabla.verticalHeaderItem(f).text() for f in range(self.ventana.tabla.rowCount())]
        fila_beto = etiquetas_filas.index("beto")

        _casilla(self.ventana.tabla, fila_beto, 0).setChecked(True)

        self.assertIn("beto", self.botones_service.listar_visibilidad(self.boton1_id))

    def test_desmarcar_activo_deshabilita_la_columna_y_persiste(self) -> None:
        _casilla(self.ventana.tabla, FILA_ACTIVO, 0).setChecked(False)

        botones = {b[0]: b for b in self.botones_service.listar_botones()}
        self.assertEqual(botones[self.boton1_id][5], 0)  # activo

        etiquetas_filas = [self.ventana.tabla.verticalHeaderItem(f).text() for f in range(self.ventana.tabla.rowCount())]
        fila_ana = etiquetas_filas.index("ana")
        self.assertFalse(_casilla(self.ventana.tabla, fila_ana, 0).isEnabled())

    def test_soltar_columna_arrastrada_renumera_en_la_base(self) -> None:
        # No se simula el QDrag real (drag.exec() es modal/bloqueante) -- se simula el efecto de
        # haber soltado ya el arrastre: el orden visual cambió (moveSection, lo que Qt ya hace
        # solo durante el drag) y toca persistirlo, exactamente lo que hace
        # TablaBotones.dropEvent al recibir el drop.
        encabezado = self.ventana.tabla.horizontalHeader()
        encabezado.moveSection(0, 1)
        orden_logico = [encabezado.logicalIndex(v) for v in range(encabezado.count())]

        self.ventana._al_soltar_columna_arrastrada(orden_logico)

        botones_ordenados = self.botones_service.listar_botones()
        self.assertEqual(botones_ordenados[0][0], self.boton2_id)
        self.assertEqual(botones_ordenados[1][0], self.boton1_id)

    def test_doble_clic_real_dispara_la_senal_un_solo_clic_no(self) -> None:
        encabezado = self.ventana.tabla.horizontalHeader()
        recibidos = []
        encabezado.dobleClicEncabezado.connect(recibidos.append)

        # La señal SIGUE conectada también a _al_doble_clic_encabezado (el de producción, que
        # abre un QMessageBox.question modal) -- sin mockearlo, el segundo clic se queda
        # esperando ese diálogo para siempre bajo QT_QPA_PLATFORM=offscreen.
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            _clic(encabezado, 0)
            self.assertEqual(recibidos, [])  # un solo clic no cuenta como doble

            _clic(encabezado, 0)
            self.assertEqual(recibidos, [0])

    def test_dos_clics_lentos_no_cuentan_como_doble_clic(self) -> None:
        encabezado = self.ventana.tabla.horizontalHeader()
        recibidos = []
        encabezado.dobleClicEncabezado.connect(recibidos.append)

        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            _clic(encabezado, 0)
            time.sleep((QApplication.doubleClickInterval() + 100) / 1000)
            _clic(encabezado, 0)

        self.assertEqual(recibidos, [])

    def test_alto_del_encabezado_se_ajusta_al_texto_mas_largo(self) -> None:
        encabezado = self.ventana.tabla.horizontalHeader()
        alto_con_dos_botones = encabezado.height()

        self.botones_service.crear_boton("boton3", "UN NOMBRE MUY LARGO DE VERDAD", "boton3", orden=2)
        self.ventana.reconstruir()

        self.assertGreater(encabezado.height(), alto_con_dos_botones)
        self.assertGreaterEqual(encabezado.height(), ALTO_ENCABEZADO_MINIMO)

    def test_doble_clic_editar_abre_dialogo_con_datos_correctos(self) -> None:
        capturado = {}

        def fake_dialogo(self_dialogo, *args, **kwargs):
            capturado["etiqueta_inicial"] = kwargs.get("etiqueta_inicial", args[1] if len(args) > 1 else "")
            capturado["archivo_inicial"] = kwargs.get("archivo_inicial", args[2] if len(args) > 2 else "")

        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             mock.patch.object(DialogoBoton, "__init__", fake_dialogo), \
             mock.patch.object(DialogoBoton, "exec", return_value=QDialog.DialogCode.Rejected):
            self.ventana._al_doble_clic_encabezado(0)

        self.assertEqual(capturado["etiqueta_inicial"], "Boton Uno")
        self.assertEqual(capturado["archivo_inicial"], "boton1")

    def test_doble_clic_eliminar_borra_el_boton(self) -> None:
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.ventana._al_doble_clic_encabezado(0)

        ids = [b[0] for b in self.botones_service.listar_botones()]
        self.assertNotIn(self.boton1_id, ids)

    def test_crear_boton_lo_agrega_al_final(self) -> None:
        with mock.patch.object(DialogoBoton, "exec", return_value=QDialog.DialogCode.Accepted), \
             mock.patch.object(DialogoBoton, "datos", return_value=("Boton Tres", "boton3")):
            self.ventana._al_crear()

        etiquetas = [b[2] for b in self.botones_service.listar_botones()]
        self.assertEqual(etiquetas, ["Boton Uno", "Boton Dos", "Boton Tres"])

    def test_casillas_quedan_centradas(self) -> None:
        for fila in (FILA_ACTIVO, 1):
            contenedor = self.ventana.tabla.cellWidget(fila, 0)
            self.assertEqual(contenedor.layout().alignment(), Qt.AlignmentFlag.AlignCenter)
            self.assertEqual(contenedor.layout().contentsMargins().left(), 0)

    def test_sin_cuadricula_ni_marco_visible(self) -> None:
        self.assertFalse(self.ventana.tabla.showGrid())
        self.assertEqual(self.ventana.tabla.frameShape(), self.ventana.tabla.frameShape().NoFrame)

    def test_barra_de_opciones_extra_queda_debajo_de_la_tabla(self) -> None:
        layout = self.ventana.centralWidget().layout()
        self.assertIs(layout.itemAt(0).widget(), self.ventana.tabla)
        self.assertIsNone(layout.itemAt(1).widget())  # es el QHBoxLayout de la barra, no un widget
        self.assertGreater(layout.count(), 1)

    def test_ventana_se_ajusta_al_contenido_sin_dejar_espacio_de_sobra(self) -> None:
        ancho_esperado = self.ventana.tabla.verticalHeader().width() + sum(
            self.ventana.tabla.columnWidth(i) for i in range(self.ventana.tabla.columnCount())
        )
        alto_esperado = self.ventana.tabla.horizontalHeader().height() + sum(
            self.ventana.tabla.rowHeight(i) for i in range(self.ventana.tabla.rowCount())
        )
        self.assertEqual(self.ventana.tabla.width(), ancho_esperado + 2)
        self.assertEqual(self.ventana.tabla.height(), alto_esperado + 2)

    def test_etiqueta_plantilla_es_default(self) -> None:
        self.assertEqual(_etiqueta_usuario(USUARIO_PLANTILLA), "DEFAULT")

    def test_traer_al_frente_no_revienta_sin_pantalla_real(self) -> None:
        # No hay ventana real que "activar" bajo QT_QPA_PLATFORM=offscreen; solo importa que la
        # señal (emitida, en producción, desde el hilo de instancia_unica.escuchar) no explote.
        self.ventana.solicitar_traer_al_frente.emit()
        self.app.processEvents()


class ReordenarHaciaTests(QtTestCase):
    """TablaBotones.reordenar_hacia en aislamiento: columnas de ancho DISTINTO a propósito (el
    caso que puede titilar si no se compara "quedaría el cursor sobre la arrastrada")."""

    def setUp(self) -> None:
        self.tabla = TablaBotones(al_soltar_columna=lambda orden: None)
        self.tabla.setColumnCount(3)
        self.tabla.setRowCount(1)
        self.tabla.setColumnWidth(0, 40)
        self.tabla.setColumnWidth(1, 100)
        self.tabla.setColumnWidth(2, 40)
        self.addCleanup(self.tabla.close)

    def test_no_reordena_si_el_cursor_no_cruzo_lo_suficiente(self) -> None:
        h = self.tabla.horizontalHeader()
        self.tabla._arrastrada = 0
        # Justo entrando a la columna 1 (ancha): con ancho 40 (la arrastrada) el cursor a un pelo
        # de cruzar a la 1 todavía no alcanza para que quedaría SOBRE la arrastrada tras mover.
        h.moveSection(0, 0)
        self.tabla.reordenar_hacia(41)
        self.assertEqual(h.visualIndex(0), 0)

    def test_reordena_cuando_el_cursor_ya_esta_bien_dentro_de_la_columna_vecina(self) -> None:
        h = self.tabla.horizontalHeader()
        self.tabla._arrastrada = 0
        h.moveSection(0, 0)
        self.tabla.reordenar_hacia(100)  # bien adentro de la columna 1 (ancha)
        self.assertEqual(h.visualIndex(0), 1)


class AltoEncabezadoTests(QtTestCase):
    def test_usa_el_minimo_sin_botones(self) -> None:
        metricas = QCheckBox().fontMetrics()  # cualquier QWidget sirve para pedir fontMetrics()
        self.assertEqual(_alto_necesario_encabezado([], metricas), ALTO_ENCABEZADO_MINIMO)

    def test_crece_con_el_texto_mas_largo(self) -> None:
        metricas = QCheckBox().fontMetrics()
        corto = _alto_necesario_encabezado(["X"], metricas)
        largo = _alto_necesario_encabezado(["UN NOMBRE MUY LARGO DE VERDAD"], metricas)
        self.assertGreater(largo, corto)


class ListarUsuariosCandidatosTests(unittest.TestCase):
    def test_plantilla_primero_luego_alfabetico(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            usuarios_service = UsuariosService(tmp.name)
            usuarios_service.asegurar_usuario_sistema(
                {"nombre_usuario": "zoe", "sistema_operativo": "Linux", "version_sistema": "", "nombre_equipo": "pc1", "dominio": ""}
            )
            usuarios_service.asegurar_usuario_sistema(
                {"nombre_usuario": "ana", "sistema_operativo": "Linux", "version_sistema": "", "nombre_equipo": "pc1", "dominio": ""}
            )
            candidatos = listar_usuarios_candidatos(usuarios_service)
            self.assertEqual(candidatos, ["__default__", "ana", "zoe"])
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
