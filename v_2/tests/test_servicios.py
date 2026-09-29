import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from services.botones_service import BotonesService
from services.catalogo_service import CatalogoService, ProductoDuplicado, ProductoEnUso, formatear_nombre
from services.codigos_barras_service import CodigosBarrasService
from services.usuarios_service import UsuariosService
from services.ventas_service import VentasService


class BaseConDb(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.db = os.path.join(self._dir.name, "ventas.db")


class TestVentas(BaseConDb):
    def test_registra_y_lista_las_ventas_del_dia(self):
        ventas = VentasService(self.db)
        ventas.registrar_venta([("blusa", 50.0, 2, 100.0)], recibido=100, cambio=0, fecha="2026-01-02", hora="10:00:00")
        ventas.registrar_evento_especial("APERTURA DE CAJA", fecha="2026-01-02", hora="10:30:00")

        filas = ventas.obtener_ventas(fecha="2026-01-02")

        self.assertEqual(filas[0], ("10:00:00", "blusa", 50.0, 2, 100.0))
        self.assertEqual(filas[1], ("10:30:00", "APERTURA DE CAJA", "", "", ""))
        self.assertEqual(ventas.obtener_ventas(fecha="2026-01-03"), [])

    def test_venta_sin_items_no_se_registra(self):
        self.assertIsNone(VentasService(self.db).registrar_venta([]))


class TestCatalogo(BaseConDb):
    def test_agregar_normaliza_y_no_permite_repetidos(self):
        catalogo = CatalogoService(self.db)
        catalogo.agregar_producto_autocompletado("  Mayón Faja ")
        self.assertEqual([p for _i, p in catalogo.listar_catalogo_autocompletado()], ["mayón faja"])
        with self.assertRaises(ProductoDuplicado):
            catalogo.agregar_producto_autocompletado("MAYÓN FAJA")
        with self.assertRaises(ValueError):
            catalogo.agregar_producto_autocompletado("   ")

    def test_busca_por_iniciales_ignorando_preposiciones_y_acentos(self):
        catalogo = CatalogoService(self.db)
        catalogo.agregar_producto_autocompletado("short de hombre")
        catalogo.agregar_producto_autocompletado("mayón faja")
        self.assertEqual([p for _i, p in catalogo.buscar_catalogo_por_iniciales("sh")], ["short de hombre"])
        self.assertEqual([p for _i, p in catalogo.buscar_catalogo_por_iniciales("MF")], ["mayón faja"])
        self.assertEqual(catalogo.buscar_catalogo_por_iniciales(""), [])
        self.assertEqual(catalogo.normalizar_prefijo("  Mayón "), "mayon")

    def test_editar_a_un_nombre_repetido_y_borrar_un_producto_con_codigos(self):
        catalogo = CatalogoService(self.db)
        a = catalogo.agregar_producto_autocompletado("blusa")
        catalogo.agregar_producto_autocompletado("short")
        with self.assertRaises(ProductoDuplicado):
            catalogo.editar_producto_autocompletado(a, "SHORT")
        CodigosBarrasService(self.db).registrar_codigo_barras("blu", a, 10)
        with self.assertRaises(ProductoEnUso):
            catalogo.eliminar_producto_autocompletado(a)

    def test_formatear_nombre_deja_las_preposiciones_en_minuscula(self):
        self.assertEqual(formatear_nombre("short DE hombre"), "Short de Hombre")


class TestCodigosBarras(BaseConDb):
    def setUp(self):
        super().setUp()
        self.catalogo = CatalogoService(self.db)
        self.codigos = CodigosBarrasService(self.db)
        self.short = self.catalogo.agregar_producto_autocompletado("short de hombre")
        self.mayon = self.catalogo.agregar_producto_autocompletado("mayón faja")
        self.codigos.registrar_codigo_barras("shom", self.short, 100)
        self.codigos.registrar_codigo_barras("c shh", self.short, 100)
        self.codigos.registrar_codigo_barras("mayfaj", self.mayon, 200)

    def test_obtener_no_distingue_mayusculas_ni_espacios_de_los_bordes(self):
        self.assertEqual(self.codigos.obtener_codigo_barras_registrado(" SHOM "), (self.short, "short de hombre", 100.0))
        self.assertIsNone(self.codigos.obtener_codigo_barras_registrado("nada"))
        self.assertIsNone(self.codigos.obtener_codigo_barras_registrado("  "))

    def test_detalle_trae_producto_precio_fecha_y_otros_codigos(self):
        detalle = self.codigos.obtener_detalle_codigo_barras("shom")
        self.assertEqual((detalle.producto, detalle.precio_venta, detalle.otros_codigos), ("short de hombre", 100.0, 1))
        self.assertTrue(detalle.creado_en)
        self.assertEqual(self.codigos.obtener_detalle_codigo_barras("mayfaj").otros_codigos, 0)
        self.assertIsNone(self.codigos.obtener_detalle_codigo_barras("zzz"))

    def test_listar_ordena_por_producto_y_filtra_sin_acentos(self):
        self.assertEqual([c.codigo_barras for c in self.codigos.listar_codigos_barras()], ["mayfaj", "c shh", "shom"])
        self.assertEqual([c.codigo_barras for c in self.codigos.listar_codigos_barras("mayon")], ["mayfaj"])
        self.assertEqual([c.codigo_barras for c in self.codigos.listar_codigos_barras("SHOM")], ["shom"])
        self.assertEqual([c.codigo_barras for c in self.codigos.listar_codigos_barras("hombre")], ["c shh", "shom"])
        self.assertEqual(self.codigos.listar_codigos_barras("xyz"), [])

    def test_no_permite_registrar_dos_veces_el_mismo_codigo(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.codigos.registrar_codigo_barras("SHOM", self.mayon, 5)
        with self.assertRaises(ValueError):
            self.codigos.registrar_codigo_barras(" ", self.mayon, 5)


class TestUsuariosYBotones(BaseConDb):
    def test_usuario_nuevo_y_sesion(self):
        usuarios = UsuariosService(self.db)
        datos = {"nombre_usuario": "ana", "sistema_operativo": "Linux", "nombre_equipo": "pc", "dominio": ""}
        usuario_id, es_nuevo = usuarios.asegurar_usuario_sistema(datos)
        self.assertTrue(es_nuevo)
        self.assertEqual(usuarios.asegurar_usuario_sistema(datos), (usuario_id, False))

        sesion = usuarios.iniciar_sesion_sistema(usuario_id, pid=1)
        usuarios.registrar_latido_sesion(sesion)
        usuarios.cerrar_sesion_sistema(sesion, exitosa=True)
        self.assertEqual(len(usuarios.listar_sesiones_sistema(usuario_id)), 1)

    def test_botones_comparten_la_misma_base(self):
        UsuariosService(self.db)
        botones = BotonesService(self.db)
        botones.crear_boton("x", "X", "x", orden=1)
        self.assertEqual([b[1] for b in botones.listar_botones()], ["x"])

    def test_set_visibilidad_actualiza_actualizado_en(self):
        # admin_botones (proceso aparte) refresca la hoja en vivo comparando resumen_cambios();
        # sin este bump, un cambio de SOLO visibilidad pasaría inadvertido. actualizado_en tiene
        # resolución de segundo (ver crear_boton/set_visibilidad), así que se fija un "ahora"
        # distinto para cada llamada en vez de confiar en que el reloj real avance entre ambas.
        usuarios = UsuariosService(self.db)
        usuarios.asegurar_usuario_sistema(
            {"nombre_usuario": "ana", "sistema_operativo": "Linux", "nombre_equipo": "pc", "dominio": ""}
        )
        botones = BotonesService(self.db)

        with mock.patch("services.botones_service.datetime") as datetime_falso:
            datetime_falso.now.return_value.strftime.return_value = "2026-01-01 00:00:00"
            boton_id = botones.crear_boton("x", "X", "x")
        antes = botones.resumen_cambios()

        with mock.patch("services.botones_service.datetime") as datetime_falso:
            datetime_falso.now.return_value.strftime.return_value = "2026-01-01 00:00:01"
            botones.set_visibilidad(boton_id, ["ana"])

        self.assertNotEqual(botones.resumen_cambios(), antes)
        self.assertEqual(botones.listar_visibilidad(boton_id), ["ana"])

    def test_resumen_cambios_nota_creacion_y_eliminacion(self):
        UsuariosService(self.db)
        botones = BotonesService(self.db)
        vacio = botones.resumen_cambios()

        boton_id = botones.crear_boton("x", "X", "x")
        con_uno = botones.resumen_cambios()
        self.assertNotEqual(con_uno, vacio)

        botones.eliminar_boton(boton_id)
        self.assertNotEqual(botones.resumen_cambios(), con_uno)


if __name__ == "__main__":
    unittest.main()
