import os
import tempfile
import unittest

from dialogs.varios_codigos import (
    ListaPiezas,
    Renglon,
    filtrar_productos,
    leyenda_con_precio,
    leer_piezas,
    leer_precio,
    textos_codigos,
    textos_renglones,
    texto_resumen,
    validar_codigo_escrito,
)
from hardware.barcode_printer import BarcodePrinter, repartir_en_etiquetas, validar_codigo
from services.catalogo_service import CatalogoService
from services.codigos_barras_service import CodigoBarras, CodigosBarrasService


def _renglon(codigo, piezas, registrado=False):
    return Renglon(codigo, 1, "blusa básica", 150.0, piezas, registrado)


class TestRepartirEnEtiquetas(unittest.TestCase):
    def test_llena_cada_etiqueta_con_codigos_distintos(self):
        self.assertEqual(
            repartir_en_etiquetas([("ABC", 2), ("XY", 4)]),
            [["ABC", "ABC", "XY"], ["XY", "XY", "XY"]],
        )

    def test_la_ultima_etiqueta_queda_con_huecos(self):
        self.assertEqual(repartir_en_etiquetas([("ABC", 1), ("XY", 3)]), [["ABC", "XY", "XY"], ["XY", None, None]])
        self.assertEqual(repartir_en_etiquetas([]), [])

    def test_una_imagen_por_etiqueta_del_tamano_de_siempre(self):
        impresora = BarcodePrinter()
        imagenes = impresora.crear_etiquetas_por_piezas([("ABC", 2), ("XYZ", 2)])
        self.assertEqual(len(imagenes), 2)
        self.assertEqual({imagen.size for imagen in imagenes}, {(impresora.ancho_px, impresora.alto_px)})

    def test_rechaza_un_codigo_que_el_codificador_no_acepta(self):
        with self.assertRaises(ValueError):
            BarcodePrinter().imprimir_por_piezas([("ABC", 3)], en_segundo_plano=False, codificador="ITF (solo números)")


class TestListaPiezas(unittest.TestCase):
    def test_cuenta_piezas_etiquetas_y_faltantes(self):
        lista = ListaPiezas()
        lista.agregar(_renglon("A1", 2))
        lista.agregar(_renglon("B2", 2))
        self.assertEqual((lista.total_piezas, lista.etiquetas, lista.faltantes), (4, 2, 2))
        lista.agregar(_renglon("C3", 2))
        self.assertEqual((lista.total_piezas, lista.etiquetas, lista.faltantes), (6, 2, 0))

    def test_un_codigo_repetido_suma_piezas_sin_distinguir_mayusculas(self):
        lista = ListaPiezas()
        lista.agregar(_renglon("abc", 1))
        lista.agregar(_renglon("ABC", 2))
        self.assertEqual(lista.piezas(), [("abc", 3)])

    def test_solo_los_nuevos_se_registran(self):
        lista = ListaPiezas()
        lista.agregar(_renglon("A1", 1, registrado=True))
        lista.agregar(_renglon("B2", 2))
        self.assertEqual(lista.nuevos(), [("B2", 1, 150.0)])

    def test_quitar(self):
        lista = ListaPiezas()
        lista.agregar(_renglon("A1", 1))
        lista.quitar(5)
        lista.quitar(0)
        self.assertEqual(lista.renglones, [])

    def test_textos(self):
        lista = ListaPiezas()
        self.assertEqual(texto_resumen(lista), "La lista está vacía.")
        lista.agregar(_renglon("A1", 1))
        self.assertEqual(textos_renglones(lista.renglones), ["A1 · Blusa Básica · $150.00 · 1 pieza (nuevo)"])
        self.assertEqual(texto_resumen(lista), "Total: 1 pieza en 1 etiqueta. Faltan 2 piezas para llenar la última etiqueta.")
        lista.agregar(_renglon("B2", 1))
        self.assertTrue(texto_resumen(lista).endswith("Falta 1 pieza para llenar la última etiqueta."))
        lista.agregar(_renglon("C3", 4))
        self.assertEqual(texto_resumen(lista), "Total: 6 piezas en 2 etiquetas.")


class TestLeyendaConPrecio(unittest.TestCase):
    def test_precio_en_centavos_pegado_al_codigo(self):
        self.assertEqual(leyenda_con_precio("ABCDEF", 100), "10000ABCDEF")
        self.assertEqual(leyenda_con_precio("A1", 150.5), "15050A1")

    def test_la_leyenda_no_cambia_las_barras(self):
        impresora = BarcodePrinter()
        con = impresora.crear_etiquetas_por_piezas([("ABC", 3)], leyendas={"ABC": "10000ABC"})[0]
        sin = impresora.crear_etiquetas_por_piezas([("ABC", 3)])[0]
        self.assertNotEqual(con.tobytes(), sin.tobytes())


class TestTextosAlineados(unittest.TestCase):
    def test_los_separadores_quedan_en_la_misma_columna(self):
        renglones = [
            Renglon("abc", 1, "blusa de rayas", 123.0, 1, False),
            Renglon("vwewfe", 2, "blusa de terciopelo", 12.0, 12, True),
        ]
        textos = textos_renglones(renglones)
        self.assertEqual(
            textos,
            [
                "abc    · Blusa de Rayas      · $123.00 ·  1 pieza  (nuevo)",
                "vwewfe · Blusa de Terciopelo ·  $12.00 · 12 piezas",
            ],
        )
        posiciones = {tuple(i for i, c in enumerate(texto) if c == "·") for texto in textos}
        self.assertEqual(len(posiciones), 1)
        self.assertEqual(textos_renglones([]), [])

    def test_codigos_registrados_en_columnas(self):
        codigos = [
            CodigoBarras(1, "abc", 1, "blusa de rayas", 123.0, None),
            CodigoBarras(2, "vwewfe", 2, "blusa de terciopelo", 12.0, None),
        ]
        self.assertEqual(
            textos_codigos(codigos),
            [
                "abc    · Blusa de Rayas      · $123.00",
                "vwewfe · Blusa de Terciopelo ·  $12.00",
            ],
        )
        self.assertEqual(textos_codigos([]), [])


class TestLecturaDeCampos(unittest.TestCase):
    def test_codigo(self):
        self.assertEqual(validar_codigo_escrito(" AB12 ", "Code 128", validar_codigo), "AB12")
        for texto in ("", "1234567"):
            with self.assertRaises(ValueError):
                validar_codigo_escrito(texto, "Code 128", validar_codigo)
        with self.assertRaises(ValueError):
            validar_codigo_escrito("ABC", "ITF (solo números)", validar_codigo)

    def test_piezas_y_precio(self):
        self.assertEqual(leer_piezas("2"), 2)
        for texto in ("", "0", "100", "x"):
            with self.assertRaises(ValueError):
                leer_piezas(texto)
        self.assertEqual(leer_precio("150,5"), 150.5)
        for texto in ("", "-1", "abc"):
            with self.assertRaises(ValueError):
                leer_precio(texto)


class TestFiltrarProductos(unittest.TestCase):
    PRODUCTOS = [(1, "blusa básica"), (2, "mayón de faja"), (3, "short")]

    def test_por_texto_o_por_iniciales_sin_acentos(self):
        self.assertEqual(filtrar_productos(self.PRODUCTOS, "BASICA"), [(1, "blusa básica")])
        self.assertEqual(filtrar_productos(self.PRODUCTOS, "mf"), [(2, "mayón de faja")])
        self.assertEqual(filtrar_productos(self.PRODUCTOS, ""), self.PRODUCTOS)


class TestRegistrarVarios(unittest.TestCase):
    def setUp(self):
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        db = os.path.join(directorio.name, "ventas.db")
        catalogo = CatalogoService(db)
        self.blusa = catalogo.agregar_producto_autocompletado("blusa")
        self.codigos = CodigosBarrasService(db)

    def test_registra_todos(self):
        self.codigos.registrar_codigos_barras([("A1", self.blusa, 100), ("B2", self.blusa, 120)])
        self.assertEqual(self.codigos.obtener_codigo_barras_registrado("b2"), (self.blusa, "blusa", 120.0))

    def test_si_uno_falla_no_registra_ninguno(self):
        self.codigos.registrar_codigo_barras("A1", self.blusa, 100)
        with self.assertRaises(Exception):
            self.codigos.registrar_codigos_barras([("B2", self.blusa, 120), ("a1", self.blusa, 90)])
        self.assertIsNone(self.codigos.obtener_codigo_barras_registrado("B2"))

    def test_la_impresion_guarda_las_piezas(self):
        self.codigos.registrar_impresion("A1", 1, codificador="Code 128", piezas=2)
        import sqlite3

        with sqlite3.connect(self.codigos.db_path) as con:
            self.assertEqual(con.execute("SELECT copias, piezas FROM impresiones_codigos_barras").fetchone(), (1, 2))


class TestAccionImprimirVarios(unittest.TestCase):
    """La acción completa con dobles: registra, descarta el borrador, imprime y deja reintentar."""

    def setUp(self):
        import importlib.util
        from types import SimpleNamespace
        from unittest import mock

        import dialogs.imprimir_varios_codigos as dialogo

        spec = importlib.util.spec_from_file_location("acciones.imprimir_varios_codigos", "acciones/imprimir_varios_codigos.py")
        self.accion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.accion)

        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        db = os.path.join(directorio.name, "ventas.db")
        catalogo = CatalogoService(db)
        self.blusa = catalogo.agregar_producto_autocompletado("blusa")
        self.codigos = CodigosBarrasService(db)
        self.ctx = SimpleNamespace(context=None, catalogo=catalogo, codigos_barras=self.codigos)

        self.lista = ListaPiezas()
        self.lista.agregar(Renglon("A1", self.blusa, "blusa", 100.0, 2, False))
        self.lista.agregar(Renglon("B2", self.blusa, "blusa", 50.0, 1, False))
        dialogo._borrador.update(lista=self.lista)
        self.dialogo = dialogo

        self.impresiones = []
        self.avisos = []
        parches = [
            mock.patch.object(self.accion, "solicitar_varios_codigos", return_value=(self.lista, "Code 128")),
            mock.patch.object(self.accion, "imprimir_por_piezas", side_effect=lambda *a, **k: self.impresiones.append((a, k))),
            mock.patch.object(self.accion, "mostrar_aviso_impresion", side_effect=lambda _c, reintentar=None: self.avisos.append(reintentar)),
            mock.patch.object(self.accion, "mostrar_aviso_error"),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def test_registra_imprime_y_reintenta(self):
        self.accion.ejecutar(self.ctx)

        self.assertEqual(self.codigos.obtener_codigo_barras_registrado("A1"), (self.blusa, "blusa", 100.0))
        self.assertEqual(self.dialogo._borrador, {})
        self.assertEqual(len(self.impresiones), 1)
        args, kwargs = self.impresiones[0]
        self.assertEqual(args[0], [("A1", 2), ("B2", 1)])
        self.assertEqual(kwargs["leyendas"], {"A1": "10000A1", "B2": "5000B2"})

        self.avisos[0]()  # "Reintentar"
        self.assertEqual(len(self.impresiones), 2)
        import sqlite3

        with sqlite3.connect(self.codigos.db_path) as con:
            filas = con.execute("SELECT codigo_barras, copias, piezas FROM impresiones_codigos_barras ORDER BY id").fetchall()
        self.assertEqual(filas, [("A1", 1, 2), ("B2", 1, 1)] * 2)

    def test_si_el_registro_falla_no_imprime_y_conserva_el_borrador(self):
        self.codigos.registrar_codigo_barras("B2", self.blusa, 50)

        self.accion.ejecutar(self.ctx)

        self.assertEqual(self.impresiones, [])
        self.assertIs(self.dialogo._borrador["lista"], self.lista)
        self.assertIsNone(self.codigos.obtener_codigo_barras_registrado("A1"))


if __name__ == "__main__":
    unittest.main()
