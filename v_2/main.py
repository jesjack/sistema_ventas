import sys
import time
from pathlib import Path

from scanner_detector import get_scanned_string, is_scan

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import uno
from table_modules import create_table
from table_modules.table_manager import TableManager
from sheet_admin import SheetAdmin
import keyboard
from rich.traceback import install
from calc_focus import enfocar_celda_sin_azul, enfocar_ventana_de_calc
from codigo_autorizacion import solicitar_codigo
from ticket_printer import TicketPrinter
from catalogo_autocompletado import abrir_editor_catalogo_autocompletado
from autocompletado_producto import AutocompletadoProductoHandler
from ventana_acciones import VentanaAcciones, crear_ventana_acciones
install(show_locals=True) # Muestra las variables locales al fallar

if __name__ == "__main__":
    # Conectar a LibreOffice
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_context)
    context = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
    desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    documento = desktop.getCurrentComponent()
    hoja = documento.Sheets[0]
    
    sheet_admin = SheetAdmin(hoja, document=documento)
    table_manager = TableManager(uno_context=context)
    controlador = documento.getCurrentController()

    with sheet_admin.temporary_unlock():
        sheet_admin.set_column_width(0, 600)
        sheet_admin.set_column_width(1, 7700)
        sheet_admin.set_column_width(2, 1600)
        sheet_admin.set_column_width(3, 600)
        sheet_admin.set_column_width(4, 2300)
        sheet_admin.set_column_width(5, 600)

        sheet_admin.set_column_width(6, 1600)
        sheet_admin.set_column_width(7, 7700)
        sheet_admin.set_column_width(8, 1600)
        sheet_admin.set_column_width(9, 600)
        sheet_admin.set_column_width(10, 2300)
        sheet_admin.set_column_width(11, 600)

        sheet_admin.format_column_as_currency(2)
        sheet_admin.format_column_as_currency(4)
        sheet_admin.format_column_as_time(6)
        sheet_admin.format_column_as_currency(8)
        sheet_admin.format_column_as_currency(10)

        input = create_table(hoja, 1, 1, ["PRODUCTO", "PRECIO", "C."])
        input.append(["", "", 1])
        input.header_color = 0x9B111E
        input.title = "INGRESE LOS DATOS"

        cart = create_table(hoja, 1, 5, ["PRODUCTO", "PRECIO", "C.", "SUBTOTAL"])
        cart.header_color = 0x1CA9C9
        cart.title = "CARRITO DE COMPRA"
        cart.show_total = True
        cart.total_label_span = 2
        cart.placeholder = "EL CARRITO ESTÁ VACÍO"
        cart.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)

        ventas = create_table(hoja, 6, 1, ["HORA", "PRODUCTO", "PRECIO", "C.", "SUBTOTAL"])
        ventas.header_color = 0x50C878
        ventas.title = "VENTAS REALIZADAS"
        ventas.show_total = True
        ventas.total_label_span = 2
        ventas.placeholder = "NO HAY VENTAS REALIZADAS"
        table_manager.load_sales(ventas)
        ventas.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)

    autocompletado_handler = AutocompletadoProductoHandler(
        context,
        documento,
        hoja,
        input,
        table_manager.ventas_service,
        sheet_admin,
    )
    controlador.addKeyHandler(autocompletado_handler)

    selling = False  # Variable para controlar la venta en curso
    def sell():
        global selling
        selling = True
        pasing = None
        with sheet_admin.temporary_unlock():
            pasing = table_manager.sell_items(cart, ventas)
        selling = False
        return pasing

    def on_scan():
        barcode = get_scanned_string(clear=True)
        print(barcode)

    def on_enter():
        global selling
        if autocompletado_handler.selector_activo:
            return
        enfocar_celda_sin_azul(documento, 1, 3)
        if selling:
            print("Venta en curso. Por favor, espere...")
            return
        if is_scan():
            print("Se detectó un escaneo. Procesando venta...")
            on_scan()
            return #TODO: Implementar procesamiento de venta por escaneo
        cobrar = False
        with sheet_admin.temporary_unlock():
            if not table_manager.add_item_to_cart(input, cart):
                cobrar = True
        if cobrar:
            if sell() == "code":
                codigo = solicitar_codigo(context)
                if codigo is not None:
                    print(f"Codigo ingresado: {codigo}")
                    if codigo == "7410":
                        try:
                            printer = TicketPrinter()
                            printer.open_cash_drawer()
                        except Exception as exc:
                            print(f"No se pudo abrir la caja: {exc}")
                        finally:
                            with sheet_admin.temporary_unlock():
                                table_manager.registrar_evento_especial(
                                    ventas,
                                    "APERTURA DE CAJA",
                                    codigo=codigo,
                                    detalle="Se abrió la caja con el código autorizado.",
                                )

    def clean_cart():
        print("Limpiando carrito...")
        with sheet_admin.temporary_unlock():
            cart.clear()

    def catalogo_autocompletado():
        abrir_editor_catalogo_autocompletado(
            context,
            ventas_service=table_manager.ventas_service,
        )

    def volver_a_la_hoja():
        enfocar_ventana_de_calc(documento)

    def registrar_atajo_accion(hotkey, accion):
        keyboard.add_hotkey(hotkey, accion)

    ventana_acciones = crear_ventana_acciones(
        context,
        titulo="Acciones de venta",
        ancho=110,
        alto=84,
        posicion="superior_derecha",
        margen=12,
        al_recuperar_foco=volver_a_la_hoja,
        registrar_atajo=registrar_atajo_accion,
    )
    ventana_acciones.agregar_boton("COBRAR CARRITO", sell)
    ventana_acciones.agregar_boton("LIMPIAR CARRITO", clean_cart)
    ventana_acciones.agregar_boton("AUTOCOMPLETADO", catalogo_autocompletado)
    ventana_acciones.mostrar()

    keyboard.add_hotkey("enter", on_enter)

    # Bucle de control: verifica si el documento sigue vivo
    try:
        while True:
            # Intentamos acceder a una propiedad básica del documento
            # Si el documento se cierra, esto lanzará una excepción (DisposedException)
            _ = documento.Title
            time.sleep(1)  # Espera 1 segundo antes de volver a verificar
    except Exception:
        # guardar excepcion en archivo
        with open("error_log.txt", "a") as f:
            f.write(f"{time.time()}: El documento ha sido cerrado o no es accesible.\n")
            f.write(f"Excepción: {str(sys.exc_info()[0])}\n")
            f.write(f"Detalles: {str(sys.exc_info()[1])}\n")
        # Si da error porque el documento ya no existe, limpiamos el teclado y cerramos
        try:
            controlador.removeKeyHandler(autocompletado_handler)
        except Exception:
            pass
        keyboard.unhook_all()