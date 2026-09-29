"""Lógica del punto de venta que antes vivía en main.py y en globals(): se prueba con dobles, sin
LibreOffice, sin teclado y sin impresora."""

import contextlib
import unittest
from pathlib import Path
from types import SimpleNamespace

from dialogs.formato import TEXTO_NO_REGISTRADO, describir_codigo, formatear_fecha_registro
from dialogs.parseo import parse_copias, parse_monto
from nucleo import caja
from nucleo.config import CODIGO_APERTURA_CAJA
from nucleo.contexto import Contexto
from nucleo.controlador_venta import ControladorVenta
from services.codigos_barras_service import CodigoBarras
from table_modules.carrito import agregar_al_carrito, total_del_carrito
from table_modules.table_manager import TableManager


class HojaFalsa:
    @contextlib.contextmanager
    def temporary_unlock(self):
        yield


class TablaFalsa(list):
    """Se comporta como Table para lo que usan el carrito y el controlador."""


class Escaner:
    def __init__(self, es_escaneo=False, texto=""):
        self.es_escaneo, self.texto, self.limpiado = es_escaneo, texto, 0

    def is_scan(self):
        return self.es_escaneo

    def get_scanned_string(self, clear=False):
        return self.texto

    def clear_buffer(self):
        self.limpiado += 1


class ServicioCodigos:
    def __init__(self, registrados=None):
        self.registrados = dict(registrados or {})
        self.nuevos = []

    def obtener_codigo_barras_registrado(self, codigo):
        return self.registrados.get(codigo)

    def registrar_codigo_barras(self, codigo, producto_id, precio_venta):
        self.nuevos.append((codigo, producto_id, precio_venta))


def crear_contexto(**extra):
    hoja = HojaFalsa()
    ctx = Contexto(
        base_dir=Path("/base"),
        context="uno",
        desktop=None,
        documento="doc",
        hoja=None,
        sheet_admin=hoja,
        table_manager=SimpleNamespace(
            add_item_to_cart=lambda entrada, carrito: agregar_al_carrito(entrada, carrito),
            registrar_evento_especial=lambda *a, **k: ctx.eventos.append((a[1], k)),
        ),
        tabla_entrada=TablaFalsa([["", "", 1]]),
        cart=TablaFalsa(),
        ventas=TablaFalsa(),
        catalogo=None,
        codigos_barras=ServicioCodigos(),
        autocompletado_handler=SimpleNamespace(selector_activo=False, seleccionar_producto=lambda: None),
    )
    ctx.eventos = []
    for clave, valor in extra.items():
        setattr(ctx, clave, valor)
    return ctx


def crear_controlador(ctx, escaner=None, **sobrescribir):
    llamadas = {"cajas": [], "foco": 0}
    dependencias = dict(
        escaner=escaner or Escaner(),
        calc_esta_enfocado=lambda ctx: True,
        enfocar_celda=lambda *a: llamadas.__setitem__("foco", llamadas["foco"] + 1),
        pedir_precio=lambda *a: 50.0,
        pedir_codigo=lambda uno: None,
        abrir_caja=lambda c, **k: llamadas["cajas"].append(k),
    )
    dependencias.update(sobrescribir)
    return ControladorVenta(ctx, **dependencias), llamadas


class TestCarrito(unittest.TestCase):
    def test_agrega_suma_y_limpia_la_entrada(self):
        entrada, carrito = TablaFalsa([["blusa", 50, 2]]), TablaFalsa()
        self.assertTrue(agregar_al_carrito(entrada, carrito))
        self.assertEqual(carrito, [("blusa", 50, 2, 100)])
        self.assertEqual(entrada, [["", "", 1]])

        entrada[0] = ["blusa", 50, 1]
        agregar_al_carrito(entrada, carrito)
        self.assertEqual(carrito, [("blusa", 50, 3, 150)])
        self.assertEqual(total_del_carrito(carrito), 150.0)

    def test_no_agrega_si_falta_un_dato(self):
        entrada, carrito = TablaFalsa([["blusa", "", 1]]), TablaFalsa()
        self.assertFalse(agregar_al_carrito(entrada, carrito))
        self.assertEqual(carrito, [])


class TestTableManager(unittest.TestCase):
    def crear(self, cobro):
        ventas = SimpleNamespace(vendidas=[], eventos=[], registrar_venta=lambda items, recibido, cambio: ventas.vendidas.append((items, recibido, cambio)))
        tickets = []
        manager = TableManager(ventas, cobro, lambda *a: tickets.append(a))
        return manager, ventas, tickets

    def test_vender_cobra_registra_imprime_y_vacia(self):
        manager, ventas, tickets = self.crear(lambda total: (100.0, 100.0 - total))
        carrito, tabla_ventas = TablaFalsa([("blusa", 50, 2, 100)]), TablaFalsa()

        self.assertIsNone(manager.sell_items(carrito, tabla_ventas))

        self.assertEqual(carrito, [])
        self.assertEqual(len(tabla_ventas), 1)
        self.assertEqual(ventas.vendidas[0][1:], (100.0, 0.0))
        self.assertEqual(tickets[0][1:], (100.0, 100.0, 0.0))

    def test_carrito_vacio_pide_codigo_y_cobro_cancelado_no_registra(self):
        manager, ventas, _ = self.crear(lambda total: None)
        self.assertEqual(manager.sell_items(TablaFalsa(), TablaFalsa()), "code")
        carrito = TablaFalsa([("blusa", 50, 1, 50)])
        self.assertIsNone(manager.sell_items(carrito, TablaFalsa()))
        self.assertEqual(ventas.vendidas, [])
        self.assertEqual(len(carrito), 1)

    def test_un_fallo_del_ticket_no_deshace_la_venta(self):
        ventas = SimpleNamespace(registrar_venta=lambda *a, **k: None)

        def falla(*a):
            raise RuntimeError("sin impresora")

        manager = TableManager(ventas, lambda total: (total, 0.0), falla)
        carrito = TablaFalsa([("blusa", 50, 1, 50)])
        manager.sell_items(carrito, TablaFalsa())
        self.assertEqual(carrito, [])


class TestControladorVenta(unittest.TestCase):
    def test_enter_sin_foco_de_calc_no_hace_nada(self):
        ctx = crear_contexto()
        escaner = Escaner()
        controlador, llamadas = crear_controlador(ctx, escaner, calc_esta_enfocado=lambda ctx: False)
        controlador.on_enter()
        self.assertEqual((llamadas["foco"], escaner.limpiado), (0, 0))

    def test_enter_agrega_al_carrito_y_siempre_limpia_el_buffer(self):
        ctx = crear_contexto()
        ctx.tabla_entrada[0] = ["blusa", 50, 1]
        escaner = Escaner()
        controlador, _ = crear_controlador(ctx, escaner)
        controlador.on_enter()
        self.assertEqual(ctx.cart, [("blusa", 50, 1, 50)])
        self.assertEqual(escaner.limpiado, 1)

    def test_no_actua_con_el_selector_abierto_ni_con_una_venta_en_curso(self):
        ctx = crear_contexto()
        ctx.tabla_entrada[0] = ["blusa", 50, 1]
        controlador, llamadas = crear_controlador(ctx)
        ctx.autocompletado_handler.selector_activo = True
        controlador.on_enter()
        ctx.autocompletado_handler.selector_activo = False
        ctx.selling = True
        controlador.on_enter()
        self.assertEqual(ctx.cart, [])

    def test_escaneo_de_un_codigo_registrado_agrega_el_producto(self):
        ctx = crear_contexto(codigos_barras=ServicioCodigos({"shom": (7, "short de hombre", 100.0)}))
        controlador, _ = crear_controlador(ctx, Escaner(es_escaneo=True, texto=" shom "))
        controlador.on_enter()
        self.assertEqual(ctx.cart, [("short de hombre", 100.0, 1, 100.0)])

    def test_escaneo_de_un_codigo_nuevo_lo_registra_con_producto_y_precio(self):
        ctx = crear_contexto()
        ctx.autocompletado_handler.seleccionar_producto = lambda: (9, "mayón faja")
        controlador, _ = crear_controlador(ctx, Escaner(es_escaneo=True, texto="nuevo"))
        controlador.on_enter()
        self.assertEqual(ctx.codigos_barras.nuevos, [("nuevo", 9, 50.0)])

    def test_escaneo_nuevo_cancelado_en_el_selector_o_en_el_precio_no_registra(self):
        ctx = crear_contexto()
        controlador, _ = crear_controlador(ctx, Escaner(es_escaneo=True, texto="nuevo"))
        controlador.on_enter()  # el selector devuelve None
        ctx.autocompletado_handler.seleccionar_producto = lambda: (9, "x")
        controlador, _ = crear_controlador(ctx, Escaner(es_escaneo=True, texto="nuevo"), pedir_precio=lambda *a: None)
        controlador.on_enter()
        self.assertEqual(ctx.codigos_barras.nuevos, [])

    def preparar_cobro_con_carrito_vacio(self, codigo):
        cobro = SimpleNamespace(ejecutar=lambda ctx: "code")
        ctx = crear_contexto(acciones={"cobrar_carrito": cobro})
        return ctx, crear_controlador(ctx, pedir_codigo=lambda uno: codigo)

    def test_carrito_vacio_con_el_codigo_autorizado_abre_la_caja(self):
        ctx, (controlador, llamadas) = self.preparar_cobro_con_carrito_vacio(CODIGO_APERTURA_CAJA)
        controlador.on_enter()
        self.assertEqual(len(llamadas["cajas"]), 1)
        self.assertEqual(llamadas["cajas"][0]["codigo"], CODIGO_APERTURA_CAJA)

    def test_otro_codigo_o_cancelar_no_abre_la_caja(self):
        for codigo in ("0000", None):
            ctx, (controlador, llamadas) = self.preparar_cobro_con_carrito_vacio(codigo)
            controlador.on_enter()
            self.assertEqual(llamadas["cajas"], [])

    def test_sin_la_accion_de_cobrar_se_deja_constancia_del_fallo(self):
        ctx = crear_contexto(acciones={})
        controlador, _ = crear_controlador(ctx)
        controlador.on_enter()
        self.assertEqual(ctx.eventos[0][0], "FALLO AL COBRAR")


class TestCaja(unittest.TestCase):
    def test_si_abre_registra_la_apertura_con_el_codigo(self):
        ctx = crear_contexto()

        class Impresora:
            def open_cash_drawer(self):
                pass

        self.assertTrue(caja.abrir_caja(ctx, "ok", codigo="7410", crear_impresora=Impresora))
        self.assertEqual(ctx.eventos, [("APERTURA DE CAJA", {"codigo": "7410", "detalle": "ok"})])

    def test_si_falla_no_registra_apertura_y_el_fallo_solo_si_se_pide(self):
        class Rota:
            def open_cash_drawer(self):
                raise OSError("sin cajón")

        ctx = crear_contexto()
        self.assertFalse(caja.abrir_caja(ctx, "ok", crear_impresora=Rota))
        self.assertEqual(ctx.eventos, [])

        self.assertFalse(caja.abrir_caja(ctx, "ok", codigo="7410", detalle_fallo="no abrió: {exc}", crear_impresora=Rota))
        self.assertEqual(ctx.eventos, [("FALLO AL ABRIR CAJA", {"codigo": "7410", "detalle": "no abrió: sin cajón"})])


class TestRedDeSeguridad(unittest.TestCase):
    """on_enter corre en un hilo de la libreria `keyboard` que no atrapa sus excepciones
    (ver el comentario de ControladorVenta.on_enter): un fallo sin atrapar mataria ese hilo
    para siempre y dejaria a Enter sin responder por el resto de la sesion. Lo mismo le pasaba
    a SheetButtonBridge con los botones. 2026-09-23: esto no dejaba rastro en el log porque la
    retencion (20 ejecuciones) rotaba la evidencia en pocos dias."""

    def test_un_fallo_inesperado_en_on_enter_no_mata_el_siguiente_enter(self):
        ctx = crear_contexto()
        ctx.tabla_entrada[0] = ["blusa", 50, 1]
        controlador, _ = crear_controlador(ctx)

        def add_item_que_falla(*a, **k):
            raise RuntimeError("UNO se cayó a mitad de la escritura")

        ctx.table_manager.add_item_to_cart = add_item_que_falla
        controlador.on_enter()  # no debe propagar

        ctx.table_manager.add_item_to_cart = lambda entrada, carrito: agregar_al_carrito(entrada, carrito)
        ctx.tabla_entrada[0] = ["blusa", 50, 1]
        controlador.on_enter()  # el siguiente Enter sigue funcionando
        self.assertEqual(ctx.cart, [("blusa", 50, 1, 50)])

    def test_el_fallo_se_imprime_con_la_etiqueta_reconocible(self):
        import io
        from contextlib import redirect_stdout

        ctx = crear_contexto()
        controlador, _ = crear_controlador(ctx, calc_esta_enfocado=lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))

        salida = io.StringIO()
        with redirect_stdout(salida):
            controlador.on_enter()

        self.assertIn("[FALLO INESPERADO] on_enter", salida.getvalue())
        self.assertIn("RuntimeError: boom", salida.getvalue())


class TestContextoCompatible(unittest.TestCase):
    def test_usar_contexto_sigue_funcionando_para_ver_camaras(self):
        from acciones._contexto import usar_contexto

        @usar_contexto
        def ejecutar(ctx):
            return BASE_DIR, cart  # noqa: F821 - vienen del contexto

        ctx = crear_contexto()
        self.assertEqual(ejecutar(ctx), (Path("/base"), ctx.cart))


class TestTextosYParseo(unittest.TestCase):
    def test_parse_monto(self):
        self.assertEqual(parse_monto("1.234,50"), 1234.5)
        self.assertEqual(parse_monto("1,234.50"), 1234.5)
        self.assertEqual(parse_monto(" 12,5 "), 12.5)
        self.assertIsNone(parse_monto(None))
        for malo in ("", "  ", "abc"):
            with self.assertRaises(ValueError):
                parse_monto(malo)

    def test_parse_copias(self):
        self.assertEqual(parse_copias(" 3 "), 3)
        with self.assertRaises(ValueError):
            parse_copias("")

    def test_describir_codigo(self):
        self.assertEqual(describir_codigo(None), TEXTO_NO_REGISTRADO)
        texto = describir_codigo(CodigoBarras(1, "shom", 2, "short de hombre", 100.0, "2026-09-09 19:55:20", 2))
        self.assertEqual(
            texto.split("\n"),
            [
                "Código ya registrado.",
                "Producto: short de hombre",
                "Precio de venta: $100.00",
                "Registrado el: 09-09-2026 19:55",
                "Otros códigos de este producto: 2",
            ],
        )
        sin_extras = describir_codigo(CodigoBarras(1, "a", 2, "x", 5, None, 0))
        self.assertNotIn("Registrado", sin_extras)
        self.assertNotIn("Otros", sin_extras)

    def test_formatear_fecha_registro(self):
        self.assertEqual(formatear_fecha_registro("2026-09-09 19:55:20"), "09-09-2026 19:55")
        self.assertEqual(formatear_fecha_registro("raro"), "raro")
        self.assertEqual(formatear_fecha_registro(None), "")


class BridgeFalso:
    def __init__(self):
        self.botones = []
        self.publicados = 0

    def reset_buttons(self):
        self.botones = []

    def add_button(self, etiqueta, manejador):
        self.botones.append(etiqueta)

    def publish_layout(self):
        self.publicados += 1


class BotonesServiceFalso:
    def __init__(self):
        self._resumen = (0, None)
        self.visibles = []

    def resumen_cambios(self):
        return self._resumen

    def listar_botones_visibles_para(self, usuario_id):
        return self.visibles

    def cambiar_resumen(self):
        self._resumen = (self._resumen[0] + 1, "algo")


class TestBotonesDeLaHoja(unittest.TestCase):
    def crear(self, usuario_actual="ana"):
        from nucleo.botones import BotonesDeLaHoja

        bridge = BridgeFalso()
        servicio = BotonesServiceFalso()
        ctx = SimpleNamespace(acciones={}, base_dir=Path("/base"))
        botones = BotonesDeLaHoja(ctx, bridge, servicio, usuario_id=1, usuario_actual=usuario_actual)
        return botones, bridge, servicio

    def test_construir_guarda_el_resumen_como_punto_de_referencia(self):
        botones, bridge, servicio = self.crear()
        botones.construir()
        self.assertEqual(bridge.publicados, 1)
        self.assertEqual(botones._ultimo_resumen, servicio.resumen_cambios())

    def test_revisar_cambios_no_reconstruye_si_nada_cambio(self):
        botones, bridge, _servicio = self.crear()
        botones.construir()
        botones.revisar_cambios()
        self.assertEqual(bridge.publicados, 1)  # no un segundo publish_layout

    def test_revisar_cambios_reconstruye_cuando_el_resumen_cambia(self):
        botones, bridge, servicio = self.crear()
        botones.construir()
        servicio.cambiar_resumen()
        botones.revisar_cambios()
        self.assertEqual(bridge.publicados, 2)

    def test_admin_raiz_ve_el_boton_administrar_admins(self):
        from nucleo.config import ADMIN_RAIZ

        botones, bridge, _servicio = self.crear(usuario_actual=ADMIN_RAIZ)
        botones.construir()
        self.assertIn("ADMINISTRAR ADMINS", bridge.botones)

    def test_usuario_normal_no_ve_administrar_admins(self):
        botones, bridge, _servicio = self.crear(usuario_actual="ana")
        botones.construir()
        self.assertNotIn("ADMINISTRAR ADMINS", bridge.botones)


if __name__ == "__main__":
    unittest.main()
