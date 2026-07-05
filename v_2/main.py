import atexit
import ctypes
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

from services.scanner_detector import clear_buffer, get_scanned_string, is_scan

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import uno
from table_modules import create_table
from table_modules.table_manager import TableManager
from calc.sheet_admin import SheetAdmin
import keyboard
from rich.traceback import install
from calc.calc_focus import enfocar_celda_sin_azul, enfocar_ventana_de_calc
from dialogs.codigo_autorizacion import solicitar_codigo
from dialogs.imprimir_codigo_barras import solicitar_datos_codigo_barras
from dialogs.seleccionar_fecha_ventas import solicitar_fecha_ventas
from dialogs.ver_ventas_del_dia import abrir_ventana_ventas_del_dia
from dialogs.precio_venta import solicitar_precio_venta
from hardware.barcode_printer import imprimir_codigo_barras
from hardware.ticket_printer import TicketPrinter
from services.seguimiento_sesion import SeguimientoSesionSistema
from ui.catalogo_autocompletado import abrir_editor_catalogo_autocompletado
from ui.autocompletado_producto import AutocompletadoProductoHandler
from ui.ventana_acciones import VentanaAcciones, crear_ventana_acciones
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
    seguimiento_sesion = None
    try:
        seguimiento_sesion = SeguimientoSesionSistema(table_manager.ventas_service)
    except Exception as exc:
        print(f"No se pudo iniciar el seguimiento de usuario: {exc}")
    else:
        atexit.register(seguimiento_sesion.cerrar)
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
        input.header_color = 0x9B111E
        input.title = "INGRESE LOS DATOS"
        input.append(["", "", 1])

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
        ventas.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)
        table_manager.load_sales(ventas)

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

    def calc_esta_enfocado():
        if sys.platform == "win32":
            # Mientras desarrollamos en Windows, validamos el foco con la ventana activa.
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False

            longitud = user32.GetWindowTextLengthW(hwnd)
            titulo = ctypes.create_unicode_buffer(longitud + 1)
            user32.GetWindowTextW(hwnd, titulo, longitud + 1)
            return "libreoffice calc" in titulo.value.lower()

        if sys.platform.startswith("linux"):
            sesion = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
            if sesion == "wayland":
                return False

            if shutil.which("xdotool") is None:
                return False

            try:
                resultado = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except Exception:
                return False

            titulo = resultado.stdout.strip().lower()
            return "libreoffice calc" in titulo or "calc" in titulo

        return False

    def on_scan():
        barcode = get_scanned_string(clear=True)
        barcode = str(barcode).strip()
        if not barcode:
            print("Escaneo vacio. No se proceso ningun codigo.")
            return

        print(f"Codigo escaneado: {barcode}")

        registro = table_manager.ventas_service.obtener_codigo_barras_registrado(barcode)
        if registro is not None:
            _producto_id, producto, precio = registro
            with sheet_admin.temporary_unlock():
                input[0] = [producto, precio, 1]
                if table_manager.add_item_to_cart(input, cart):
                    print(f"Producto agregado al carrito: {producto} (${precio:.2f})")
                else:
                    print("No se pudo agregar el producto al carrito.")
            return

        print(f"Codigo no registrado: {barcode}. Abriendo selector de autocompletado...")
        seleccionado = autocompletado_handler.seleccionar_producto()
        if seleccionado is None:
            print("Registro de codigo cancelado por el usuario.")
            return

        producto_id, producto = seleccionado

        precio = solicitar_precio_venta(context, producto, barcode)
        if precio is None:
            print("Registro de codigo cancelado al pedir el precio.")
            return

        try:
            table_manager.ventas_service.registrar_codigo_barras(barcode, producto_id=producto_id, precio_venta=precio)
            print(f"Codigo registrado: {barcode} -> {producto} (${precio:.2f})")
        except Exception as exc:
            print(f"No se pudo registrar el codigo de barras: {exc}")

    def on_enter():
        global selling
        try:
            if autocompletado_handler.selector_activo:
                return
            # if not calc_esta_enfocado():
            #     return
            enfocar_celda_sin_azul(documento, 1, 3)
            if selling:
                print("Venta en curso. Por favor, espere...")
                return
            if is_scan(min_length=2):
                print("Se detectó un escaneo. Procesando venta...")
                on_scan()
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
        finally:
            clear_buffer()

    def clean_cart():
        print("Limpiando carrito...")
        with sheet_admin.temporary_unlock():
            cart.clear()

    def catalogo_autocompletado():
        abrir_editor_catalogo_autocompletado(
            context,
            ventas_service=table_manager.ventas_service,
        )

    def ver_ventas_por_fecha():
        fecha = solicitar_fecha_ventas(context)
        if fecha is None:
            return

        abrir_ventana_ventas_del_dia(context, table_manager.ventas_service, fecha)
        print(f"Ventas consultadas para la fecha {fecha}")

    def imprimir_codigo_barras_manual():
        datos = solicitar_datos_codigo_barras(context)
        if datos is None:
            return

        codigo, copias = datos
        try:
            imprimir_codigo_barras(codigo, numero_copias=copias, density=1)
            print(f"Codigo de barras impreso: {codigo} ({copias} copias)")
        except Exception as exc:
            print(f"No se pudo imprimir el codigo de barras: {exc}")

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
    admins = ["jesjack", "nancy"]
    ventana_acciones.agregar_boton("COBRAR CARRITO", sell)
    ventana_acciones.agregar_boton("LIMPIAR CARRITO", clean_cart)
    ventana_acciones.agregar_boton("VER VENTAS", ver_ventas_por_fecha, admins)
    ventana_acciones.agregar_boton("AUTOCOMPLETADO", catalogo_autocompletado, admins)
    ventana_acciones.agregar_boton("IMPRIMIR CODIGO DE BARRAS", imprimir_codigo_barras_manual, admins)
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
        with open(LOGS_DIR / "error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"{time.time()}: El documento ha sido cerrado o no es accesible.\n")
            f.write(f"Excepción: {str(sys.exc_info()[0])}\n")
            f.write(f"Detalles: {str(sys.exc_info()[1])}\n")
        if seguimiento_sesion is not None:
            try:
                seguimiento_sesion.cerrar(exitosa=False)
            except Exception:
                pass
        # Si da error porque el documento ya no existe, limpiamos el teclado y cerramos
        try:
            controlador.removeKeyHandler(autocompletado_handler)
        except Exception:
            pass
        keyboard.unhook_all()