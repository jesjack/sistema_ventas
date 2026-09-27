"""Qué pasa cuando se pulsa Enter en la hoja: agregar al carrito, cobrar, registrar un código de
barras escaneado o abrir la caja con el código autorizado.

Antes eran funciones anidadas en main.py. Aquí todo lo externo (escáner, diálogos, caja, foco de
Calc) llega por el constructor, así que se puede probar sin LibreOffice ni teclado."""

import traceback

from nucleo.config import CODIGO_APERTURA_CAJA
from nucleo.historial import registrar_evento_de_fallo


class ControladorVenta:
    def __init__(
        self,
        ctx,
        *,
        escaner,  # is_scan(), get_scanned_string(clear=), clear_buffer()
        calc_esta_enfocado,  # (ctx=uno_context) -> bool
        enfocar_celda,  # (documento, columna, fila)
        pedir_precio,  # (uno_context, producto, codigo_barras) -> float | None
        pedir_codigo,  # (uno_context) -> str | None
        abrir_caja,  # (ctx, detalle_ok, codigo=, detalle_fallo=) -> bool
    ):
        self.ctx = ctx
        self._escaner = escaner
        self._calc_esta_enfocado = calc_esta_enfocado
        self._enfocar_celda = enfocar_celda
        self._pedir_precio = pedir_precio
        self._pedir_codigo = pedir_codigo
        self._abrir_caja = abrir_caja

    def on_scan(self):
        ctx = self.ctx
        barcode = str(self._escaner.get_scanned_string(clear=True)).strip()
        if not barcode:
            print("Escaneo vacio. No se proceso ningun codigo.")
            return

        print(f"Codigo escaneado: {barcode}")

        registro = ctx.codigos_barras.obtener_codigo_barras_registrado(barcode)
        if registro is not None:
            _producto_id, producto, precio = registro
            with ctx.sheet_admin.temporary_unlock():
                ctx.tabla_entrada[0] = [producto, precio, 1]
                if ctx.table_manager.add_item_to_cart(ctx.tabla_entrada, ctx.cart):
                    print(f"Producto agregado al carrito: {producto} (${precio:.2f})")
                else:
                    print("No se pudo agregar el producto al carrito.")
            return

        print(f"Codigo no registrado: {barcode}. Abriendo selector de autocompletado...")
        seleccionado = ctx.autocompletado_handler.seleccionar_producto()
        if seleccionado is None:
            print("Registro de codigo cancelado por el usuario.")
            return

        producto_id, producto = seleccionado

        precio = self._pedir_precio(ctx.context, producto, barcode)
        if precio is None:
            print("Registro de codigo cancelado al pedir el precio.")
            return

        try:
            ctx.codigos_barras.registrar_codigo_barras(barcode, producto_id=producto_id, precio_venta=precio)
            print(f"Codigo registrado: {barcode} -> {producto} (${precio:.2f})")
        except Exception as exc:
            print(f"No se pudo registrar el codigo de barras: {exc}")

    def on_enter(self):
        # Red de seguridad: on_enter corre en el hilo propio de la libreria `keyboard`
        # (ver keyboard._generic.GenericListener.process), que NO atrapa las excepciones
        # de un hotkey no bloqueante (add_hotkey(..., suppress=False), que es lo que usa
        # nucleo.arranque). Un error aqui sin atrapar mata ese hilo para siempre: Enter deja
        # de responder por el resto de la sesion, y si el error cae justo entre el
        # unprotect() y el protect() de sheet_admin.temporary_unlock(), la hoja puede quedar
        # sin proteger. Envolver todo el cuerpo evita ambas cosas: se pierde ese Enter, pero
        # el siguiente ya funciona, y el motivo queda en el log en vez de perderse en
        # silencio (ver NOTAS del 2026-09-23).
        try:
            self._on_enter()
        except Exception:
            print(f"[FALLO INESPERADO] on_enter: {traceback.format_exc()}")

    def _on_enter(self):
        ctx = self.ctx
        if not self._calc_esta_enfocado(ctx=ctx.context):
            print("Calc no tiene el foco. Ignorando la tecla Enter.")
            return
        print("Tecla Enter detectada. Verificando si hay un escaneo...")
        try:
            if ctx.autocompletado_handler.selector_activo:
                return
            self._enfocar_celda(ctx.documento, 1, 3)
            if ctx.selling:
                print("Venta en curso. Por favor, espere...")
                return
            if self._escaner.is_scan():
                print("Se detectó un escaneo. Procesando venta...")
                self.on_scan()
                return
            cobrar = False
            with ctx.sheet_admin.temporary_unlock():
                if not ctx.table_manager.add_item_to_cart(ctx.tabla_entrada, ctx.cart):
                    cobrar = True
            if cobrar:
                self._cobrar()
        finally:
            self._escaner.clear_buffer()

    def _cobrar(self):
        ctx = self.ctx
        accion_cobrar = ctx.acciones.get("cobrar_carrito")
        if accion_cobrar is None:
            print("[acciones] Falta acciones/cobrar_carrito.py: no se puede cobrar.")
            registrar_evento_de_fallo(
                ctx,
                "FALLO AL COBRAR",
                "No se pudo cobrar el carrito: falta acciones/cobrar_carrito.py.",
            )
            return

        # Con el carrito vacío, cobrar devuelve "code": se pide el código que autoriza abrir la caja.
        if accion_cobrar.ejecutar(ctx) != "code":
            return

        codigo = self._pedir_codigo(ctx.context)
        if codigo is None:
            return

        print(f"Codigo ingresado: {codigo}")
        if codigo == CODIGO_APERTURA_CAJA:
            self._abrir_caja(
                ctx,
                detalle_ok="Se abrió la caja con el código autorizado.",
                codigo=codigo,
                detalle_fallo="Se ingresó el código autorizado, pero no se pudo abrir la caja: {exc}",
            )
