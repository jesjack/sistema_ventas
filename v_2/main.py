from calc.calc_window_focus import es_libreoffice_calc_enfocado


def dvr_app():
    # Import diferido: dvr_timeline_app usa tkinter, que no esta disponible en
    # el Python embebido de LibreOffice. Importarlo aqui (solo al hacer clic en
    # "VER CAMARAS") evita que todo el sistema de ventas truene al arrancar.
    from cameras.dvr_timeline_app import main as _dvr_main

    _dvr_main()

print("Iniciando sistema de ventas...")

import atexit
import getpass
import os
import sys
import time
from pathlib import Path

from services.scanner_detector import clear_buffer, get_scanned_string, is_scan

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import uno
except ImportError:
    print("Warning: 'uno' module not found. Make sure you're running from LibreOffice Python.")
    sys.exit(1)

from table_modules import Table, create_table, attach_existing
from table_modules.table_manager import TableManager
from calc.sheet_admin import SheetAdmin
import keyboard
from rich.traceback import install
from calc.calc_focus import enfocar_celda_sin_azul, enfocar_ventana_de_calc, registrar_seguimiento_foco_calc
from dialogs.codigo_autorizacion import solicitar_codigo
from dialogs.aviso_impresion import mostrar_aviso_impresion
from dialogs.imprimir_codigo_barras import solicitar_datos_codigo_barras
from dialogs.seleccionar_fecha_ventas import solicitar_fecha_ventas
from dialogs.ver_ventas_del_dia import abrir_ventana_ventas_del_dia
from dialogs.precio_venta import solicitar_precio_venta
from hardware.barcode_printer import imprimir_codigo_barras
from hardware.ticket_printer import TicketPrinter
from services.button_bridge import SheetButtonBridge
from services.seguimiento_sesion import SeguimientoSesionSistema
from ui.catalogo_autocompletado import abrir_editor_catalogo_autocompletado
from ui.autocompletado_producto import AutocompletadoProductoHandler
install(show_locals=True) # Muestra las variables locales al fallar


def obtener_usuario_actual():
    for clave in ("SUDO_USER", "PKEXEC_UID"):
        valor = os.environ.get(clave)
        if not valor:
            continue

        if clave == "PKEXEC_UID":
            try:
                import pwd

                valor = pwd.getpwuid(int(valor)).pw_name
            except Exception:
                continue

        valor = str(valor).strip()
        if valor and valor.lower() != "root":
            return valor.lower()

    for obtenedor in (getpass.getuser, os.getlogin):
        try:
            valor = obtenedor()
            if valor:
                return str(valor).strip().lower()
        except Exception:
            pass

    for clave in ("USER", "USERNAME"):
        valor = os.environ.get(clave)
        if valor:
            return str(valor).strip().lower()

    return "desconocido"


def obtener_documento_calc(desktop):
    componente = desktop.getCurrentComponent()
    if componente is not None:
        try:
            if hasattr(componente, "supportsService") and componente.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                return componente
            if hasattr(componente, "getSheets"):
                return componente
        except Exception:
            pass

    componentes = desktop.getComponents().createEnumeration()
    while componentes.hasMoreElements():
        componente = componentes.nextElement()
        try:
            if hasattr(componente, "supportsService") and componente.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                return componente
            if hasattr(componente, "getSheets"):
                return componente
        except Exception:
            continue

    return None

if __name__ == "__main__":
    # Conectar a LibreOffice
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_context)
    context = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
    desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    documento = obtener_documento_calc(desktop)
    if documento is None:
        print("No se encontro un documento de Calc abierto.")
        sys.exit(1)

    hojas = documento.getSheets()
    hoja = hojas.getByIndex(0)

    # conectar_y_verificar_foco(ctx=context)
    
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
    registrar_seguimiento_foco_calc(documento)

    # ventas_rows_now se necesita en ambos caminos (fast/slow) de cualquier forma,
    # es una consulta sqlite local barata.
    ventas_rows_now = table_manager.ventas_service.obtener_ventas()

    # Chequeo minimo de sanidad: si el titulo de "ventas" ya esta en la hoja,
    # asumimos que prebake_ventas.py corrio antes de abrir soffice y nos
    # enganchamos a lo ya renderizado en vez de reconstruirlo con UNO.
    prebaked = False
    try:
        prebaked = hoja.getCellByPosition(6, 1).String == "VENTAS REALIZADAS"
    except Exception:
        prebaked = False

    with sheet_admin.temporary_unlock():
        if prebaked:
            try:
                input = attach_existing(
                    hoja, 1, 1, ["PRODUCTO", "PRECIO", "C."],
                    header_color=0x9B111E, title="INGRESE LOS DATOS",
                    rows=[("", "", 1)],
                )
                cart = attach_existing(
                    hoja, 1, 5, ["PRODUCTO", "PRECIO", "C.", "SUBTOTAL"],
                    header_color=0x1CA9C9, title="CARRITO DE COMPRA",
                    show_total=True, total_label_span=2,
                    placeholder="EL CARRITO ESTÁ VACÍO", rows=[],
                )
                ventas = attach_existing(
                    hoja, 6, 1, ["HORA", "PRODUCTO", "PRECIO", "C.", "SUBTOTAL"],
                    header_color=0x50C878, title="VENTAS REALIZADAS",
                    show_total=True, total_label_span=2,
                    placeholder="NO HAY VENTAS REALIZADAS", rows=ventas_rows_now,
                )
            except Exception as exc:
                print(f"No se pudo usar la hoja pre-horneada, reconstruyendo en vivo: {exc}")
                prebaked = False

        if not prebaked:
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

            ventas = create_table(hoja, 6, 1, ["HORA", "PRODUCTO", "PRECIO", "C.", "SUBTOTAL"])
            ventas.header_color = 0x50C878
            ventas.title = "VENTAS REALIZADAS"
            ventas.show_total = True
            ventas.total_label_span = 2
            ventas.placeholder = "NO HAY VENTAS REALIZADAS"
            table_manager.load_sales(ventas)

        cart.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)
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
        if not es_libreoffice_calc_enfocado(ctx=context):
            print("Calc no tiene el foco. Ignorando la tecla Enter.")
            return
        print("Tecla Enter detectada. Verificando si hay un escaneo...")
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
            if is_scan():
                print("Se detectó un escaneo. Procesando venta...")
                on_scan()
                return
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

    def clear_cart():
        print("Limpiando carrito...")
        with sheet_admin.temporary_unlock():
            cart.clear()

    def autocomplete():
        abrir_editor_catalogo_autocompletado(
            context,
            ventas_service=table_manager.ventas_service,
        )

    def view_sales():
        fecha = solicitar_fecha_ventas(context)
        if fecha is None:
            return

        abrir_ventana_ventas_del_dia(context, table_manager.ventas_service, fecha)
        print(f"Ventas consultadas para la fecha {fecha}")

    def print_barcode():
        datos = solicitar_datos_codigo_barras(context)
        if datos is None:
            return

        codigo, copias = datos
        try:
            imprimir_codigo_barras(codigo, numero_copias=copias, density=1, en_segundo_plano=True)
            mostrar_aviso_impresion(context)
            print(f"Codigo de barras enviado a impresion: {codigo} ({copias} copias)")
        except Exception as exc:
            print(f"No se pudo imprimir el codigo de barras: {exc}")

    admins = ["jesjack", "nancycastanedaaparicio"]
    usuario_actual = obtener_usuario_actual()

    bridge = SheetButtonBridge(context, documento, BASE_DIR)
    bridge.add_button("COBRAR CARRITO", sell)
    bridge.add_button("LIMPIAR CARRITO", clear_cart)

    if usuario_actual in admins:
        bridge.add_button("VER VENTAS", view_sales)
        bridge.add_button("AUTOCOMPLETADO", autocomplete)
        bridge.add_button("IMPRIMIR CODIGO DE BARRAS", print_barcode)
        bridge.add_button("VER CAMARAS", dvr_app)

    bridge.activate(clear_events=True)
    atexit.register(bridge.close)

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
        try:
            bridge.close()
        except Exception:
            pass
        # Si da error porque el documento ya no existe, limpiamos el teclado y cerramos
        try:
            controlador.removeKeyHandler(autocompletado_handler)
        except Exception:
            pass
        keyboard.unhook_all()