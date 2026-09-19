import atexit
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Antes de cualquier import local: los de más abajo dependen de esto.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"
DEBUG_LOGS_DIR = LOGS_DIR / "debug"
DEBUG_RUNS_TO_KEEP = 20
ADMIN_RAIZ = "jesjack"
# Salida inesperada del documento: cuántos relanzamientos seguidos se permiten
# y cuánto tiempo estable (desde el último intento) los reinicia.
MAX_RELANZAMIENTOS_POR_FALLO = 2
VENTANA_RELANZAMIENTOS_SEGUNDOS = 600
# Así se ve el cierre normal del documento (X, Alt+F4, botones, cambio de
# modo): documento.Title lanza esta excepción, "cannot get value Title".
# Observado en el 100 % de las salidas de logs/debug (18 de 18 hasta el
# 2026-09-19, incluida una provocada a propósito ese día).
EXCEPCION_CIERRE_NORMAL = "UnknownPropertyException"


_SECUENCIA_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class _SinColor:
    """Envuelve un archivo y le quita las secuencias de color ANSI: la consola
    sí las quiere (rich colorea los tracebacks), pero en el log de depuración
    serían solo ruido ilegible."""

    def __init__(self, archivo):
        self._archivo = archivo

    def write(self, data):
        return self._archivo.write(_SECUENCIA_ANSI.sub("", data))

    def flush(self):
        self._archivo.flush()

    def __getattr__(self, nombre):
        archivo = self.__dict__.get("_archivo")
        if archivo is None:
            raise AttributeError(nombre)
        return getattr(archivo, nombre)


class _Tee:
    """Escribe a varios streams a la vez (ej. consola + archivo de debug),
    sin que un fallo de uno (ej. la consola ya cerrada) tumbe la escritura a
    los demás.

    Cualquier otro atributo (isatty, encoding, fileno...) se delega al primer
    stream, para que librerías como rich sigan viendo una consola real."""

    def __init__(self, *streams):
        # sys.stdout/sys.stderr pueden ser None (ej. sin consola adjunta).
        self._streams = [s for s in streams if s is not None]

    def __getattr__(self, nombre):
        streams = self.__dict__.get("_streams")
        if not streams:
            raise AttributeError(nombre)
        return getattr(streams[0], nombre)

    def write(self, data):
        for stream in self._streams:
            try:
                stream.write(data)
            except Exception:
                pass

    def flush(self):
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                pass


def _activar_log_de_depuracion():
    """Espeja todo stdout/stderr de este proceso (prints, tracebacks
    incluyendo el que arma rich.traceback.install) a un archivo nuevo por
    ejecucion en logs/debug/, ademas de la consola -- para poder diagnosticar
    un error que la consola cerro antes de que alguien alcanzara a copiarlo.
    Se llama a esto lo antes posible (antes de cualquier otro import), para
    que incluso un fallo temprano (ej. el import de "uno" mas abajo) quede
    capturado.

    Se retienen solo las ultimas DEBUG_RUNS_TO_KEEP ejecuciones (el nombre de
    archivo trae timestamp, asi que ordenar por nombre ya da el mas
    reciente) -- suficiente para no perder evidencia si el sistema se
    reabrio una o dos veces entre que ocurrio el error y se reporta, sin
    crecer sin limite para siempre.
    """
    DEBUG_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    existentes = sorted(DEBUG_LOGS_DIR.glob("run_*.log"))
    for viejo in existentes[: max(0, len(existentes) - (DEBUG_RUNS_TO_KEEP - 1))]:
        try:
            viejo.unlink()
        except OSError:
            pass

    nombre = datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
    archivo = open(DEBUG_LOGS_DIR / nombre, "a", encoding="utf-8", buffering=1)
    # Se registra primero para que, por el orden inverso de atexit, el archivo
    # se cierre al final, después de los demás cierres que aún impriman algo.
    atexit.register(archivo.close)
    archivo_sin_color = _SinColor(archivo)
    sys.stdout = _Tee(sys.stdout, archivo_sin_color)
    sys.stderr = _Tee(sys.stderr, archivo_sin_color)


_activar_log_de_depuracion()

import os
from calc.calc_window_focus import es_libreoffice_calc_enfocado

print("Iniciando sistema de ventas...")

import time

from services.scanner_detector import clear_buffer, get_scanned_string, is_scan

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
from dialogs.aviso_error import mostrar_aviso_error
from dialogs.imprimir_codigo_barras import solicitar_datos_codigo_barras
from dialogs.seleccionar_fecha_ventas import solicitar_fecha_ventas
from dialogs.precio_venta import solicitar_precio_venta
from hardware.barcode_printer import imprimir_codigo_barras
from hardware.ticket_printer import TicketPrinter
from services.button_bridge import SheetButtonBridge
from services.identidad import obtener_usuario_actual
from services.instancia_unica import asegurar_instancia_unica
from services.modo_sistema import (
    leer_modo,
    escribir_modo,
    solicitar_relanzamiento,
    registrar_intento_relanzamiento_por_fallo,
    reiniciar_intentos_relanzamiento_por_fallo,
)
from services.seguimiento_sesion import SeguimientoSesionSistema
from services.ventas_service import VentasService
from services.botones_service import BotonesService
from services.accion_registry import cargar_acciones
from ui.catalogo_autocompletado import abrir_editor_catalogo_autocompletado
from ui.autocompletado_producto import AutocompletadoProductoHandler
install(show_locals=True) # Muestra las variables locales al fallar


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


def vigilar_documento(documento):
    """Bloquea mientras el documento siga vivo; al dejar de responder
    (cerrado con X, Alt+F4, botones o el ciclo de cambio de modo) devuelve la
    excepción que lo delató."""
    try:
        while True:
            # Si el documento se cierra, acceder a una propiedad básica lanza
            # una excepción.
            _ = documento.Title
            # main.ods nunca persiste datos por sí mismo (es solo una
            # interfaz sobre ventas.db, re-horneada por prebake_ventas.py en
            # cada apertura) -- resetear esto aquí, una vez por segundo, evita
            # el prompt de "¿guardar cambios?" al cerrar sin importar el
            # motivo, sin necesitar un listener de modificación reactivo.
            documento.setModified(False)
            time.sleep(1)
    except Exception as exc:
        return exc


def fue_cierre_normal_del_documento(exc):
    """True si `exc` es como se ve el cierre normal del documento (ver
    EXCEPCION_CIERRE_NORMAL). Cualquier otra excepción (ej. DisposedException
    porque soffice se cayó) NO cuenta como cierre normal."""
    return type(exc).__name__.endswith(EXCEPCION_CIERRE_NORMAL)


def resolver_salida_del_documento(exc):
    """Decide qué pasa tras dejar de responder el documento. Devuelve True si
    fue un cierre normal.

    - Cierre normal: se limpia el contador de relanzamientos y se sigue con el
      cierre de siempre (open_system.sh/.bat terminan si no hay relanzar.flag).
    - Cualquier otra excepción: se pide relanzar con el mismo mecanismo del
      cambio de modo (relanzar.flag), hasta MAX_RELANZAMIENTOS_POR_FALLO veces
      seguidas; después se cierra sin relanzar, para no ciclar sin fin.
      El flag solo lo consume el launcher cuando soffice termina, y eso lo
      hace terminar_libreoffice() al final del flujo de cada modo.
    """
    if fue_cierre_normal_del_documento(exc):
        reiniciar_intentos_relanzamiento_por_fallo()
        return True

    if registrar_intento_relanzamiento_por_fallo(
        MAX_RELANZAMIENTOS_POR_FALLO, VENTANA_RELANZAMIENTOS_SEGUNDOS
    ):
        print("[relanzamiento] Salida inesperada del documento: se relanza el sistema.")
        solicitar_relanzamiento()
    else:
        print(
            f"[relanzamiento] Salida inesperada y ya se agotaron los "
            f"{MAX_RELANZAMIENTOS_POR_FALLO} relanzamientos permitidos: no se relanza."
        )
    return False


def terminar_libreoffice(desktop):
    # Cerrar el documento (X, o el ciclo de cambio de modo) no mata el proceso
    # de soffice -- LibreOffice deja un "quickstarter" corriendo en segundo
    # plano. open_system.bat/.sh esperan a que el PROCESO termine para decidir
    # si relanzar, así que hay que forzar el cierre completo de la aplicación
    # aquí, no solo del documento.
    try:
        desktop.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    # Solo un usuario a la vez: si otro tiene el puerto de LibreOffice, se le
    # cierra su sistema y este proceso sale para que open_system.sh relance
    # (ver services/instancia_unica.py).
    if not asegurar_instancia_unica():
        sys.exit(0)

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

    sheet_admin = SheetAdmin(hoja, document=documento)
    controlador = documento.getCurrentController()
    registrar_seguimiento_foco_calc(documento)

    modo_info = leer_modo()
    modo = modo_info.get("modo", "normal")

    if modo == "ventas_dia":
        # ---- Flujo de solo lectura: mostrar las ventas de una fecha, con un
        # unico boton para regresar al sistema principal. prebake_ventas.py ya
        # horneo la tabla unica "VENTAS DEL DIA {fecha}" antes de que soffice
        # abriera el archivo -- aqui solo nos enganchamos a lo ya renderizado,
        # igual que hace el flujo normal cuando detecta pre-horneado.
        fecha = modo_info.get("fecha") or datetime.now().strftime("%Y-%m-%d")
        ventas_service = VentasService()
        ventas_rows_now = ventas_service.obtener_ventas(fecha=fecha)

        with sheet_admin.temporary_unlock():
            ventas = attach_existing(
                hoja, 6, 1, ["HORA", "PRODUCTO", "PRECIO", "C.", "SUBTOTAL"],
                header_color=0x50C878, title=f"VENTAS DEL DÍA {fecha}",
                show_total=True, total_label_span=2,
                placeholder="NO HAY VENTAS REALIZADAS", rows=ventas_rows_now,
            )

        def regresar_sistema_principal():
            escribir_modo("normal")
            solicitar_relanzamiento()
            print("Regresando al sistema principal...")
            desktop.terminate()

        bridge = SheetButtonBridge(context, documento, BASE_DIR)
        bridge.add_button("REGRESAR AL SISTEMA PRINCIPAL", regresar_sistema_principal)
        bridge.activate(clear_events=True)
        atexit.register(bridge.close)

        exc = vigilar_documento(documento)
        print(f"El documento (modo ventas_dia) ha sido cerrado o no es accesible: {type(exc)}: {exc}")
        resolver_salida_del_documento(exc)
        try:
            bridge.close()
        except Exception:
            pass
        terminar_libreoffice(desktop)

    else:
        table_manager = TableManager(uno_context=context)

        # Se resuelve aqui afuera (no adentro de SeguimientoSesionSistema)
        # para que la visibilidad de botones nunca dependa de que el hilo de
        # latido de sesion arranque bien -- si eso falla mas abajo, igual
        # queremos poder armar los botones de este usuario.
        try:
            desactivados = table_manager.ventas_service.sincronizar_usuarios_con_sistema()
            if desactivados:
                print(f"[usuarios] {desactivados} usuario(s) cambiaron de estado al sincronizar con el sistema.")
        except Exception as exc:
            print(f"[usuarios] No se pudo sincronizar la lista de usuarios: {exc}")

        # Si la base no responde aquí, el punto de venta debe arrancar de todos
        # modos (Enter/escaneo siguen funcionando); sin usuario_id solo se
        # pierden los botones por usuario y el seguimiento de sesión.
        usuario_id, usuario_es_nuevo = None, False
        try:
            usuario_id, usuario_es_nuevo = table_manager.ventas_service.asegurar_usuario_sistema()
        except Exception as exc:
            print(f"[usuarios] No se pudo registrar al usuario del sistema: {exc}")
            try:
                mostrar_aviso_error(
                    context,
                    "No se pudo registrar a tu usuario en la base de datos.\n\n"
                    "El sistema seguirá funcionando para vender, pero sin tus botones "
                    "personalizados ni el seguimiento de sesión. Reinícialo; si el "
                    "problema continúa, avisa al administrador.\n\n"
                    f"Detalle: {exc}",
                    titulo="Error al iniciar sesión",
                )
            except Exception as exc_dialogo:
                print(f"[usuarios] No se pudo mostrar el aviso en pantalla: {exc_dialogo}")

        seguimiento_sesion = None
        if usuario_id is not None:
            try:
                seguimiento_sesion = SeguimientoSesionSistema(table_manager.ventas_service, usuario_id)
            except Exception as exc:
                print(f"No se pudo iniciar el seguimiento de usuario: {exc}")
            else:
                atexit.register(seguimiento_sesion.cerrar)

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
                    tabla_entrada = attach_existing(
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
                tabla_entrada = create_table(hoja, 1, 1, ["PRODUCTO", "PRECIO", "C."])
                tabla_entrada.header_color = 0x9B111E
                tabla_entrada.title = "INGRESE LOS DATOS"
                tabla_entrada.append(["", "", 1])

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
            tabla_entrada,
            table_manager.ventas_service,
            sheet_admin,
        )
        controlador.addKeyHandler(autocompletado_handler)

        # Mutada por acciones/cobrar_carrito.py (via ctx["selling"], que es
        # este mismo global -- ctx es literalmente globals() de este modulo).
        selling = False

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
                    tabla_entrada[0] = [producto, precio, 1]
                    if table_manager.add_item_to_cart(tabla_entrada, cart):
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

        def registrar_evento_de_fallo(evento, detalle, codigo=None):
            # El historial es evidencia: si registrar el fallo también falla
            # (ej. base bloqueada), se avisa por consola pero no se propaga,
            # para no tumbar on_enter encima del error original.
            try:
                with sheet_admin.temporary_unlock():
                    table_manager.registrar_evento_especial(
                        ventas, evento, codigo=codigo, detalle=detalle,
                    )
            except Exception as exc:
                print(f"No se pudo registrar el evento '{evento}' en el historial: {exc}")

        def on_enter():
            if not es_libreoffice_calc_enfocado(ctx=context):
                print("Calc no tiene el foco. Ignorando la tecla Enter.")
                return
            print("Tecla Enter detectada. Verificando si hay un escaneo...")
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
                    if not table_manager.add_item_to_cart(tabla_entrada, cart):
                        cobrar = True
                if cobrar:
                    accion_cobrar = ACCIONES.get("cobrar_carrito")
                    if accion_cobrar is None:
                        print("[acciones] Falta acciones/cobrar_carrito.py: no se puede cobrar.")
                        registrar_evento_de_fallo(
                            "FALLO AL COBRAR",
                            "No se pudo cobrar el carrito: falta acciones/cobrar_carrito.py.",
                        )
                        return
                    if accion_cobrar.ejecutar(globals()) == "code":
                        codigo = solicitar_codigo(context)
                        if codigo is not None:
                            print(f"Codigo ingresado: {codigo}")
                            if codigo == "7410":
                                try:
                                    printer = TicketPrinter()
                                    printer.open_cash_drawer()
                                except Exception as exc:
                                    print(f"No se pudo abrir la caja: {exc}")
                                    registrar_evento_de_fallo(
                                        "FALLO AL ABRIR CAJA",
                                        f"Se ingresó el código autorizado, pero no se pudo abrir la caja: {exc}",
                                        codigo=codigo,
                                    )
                                else:
                                    # Solo se audita la apertura si de verdad
                                    # ocurrió: un fallo de la impresora no debe
                                    # dejar un evento que diga que se abrio.
                                    with sheet_admin.temporary_unlock():
                                        table_manager.registrar_evento_especial(
                                            ventas,
                                            "APERTURA DE CAJA",
                                            codigo=codigo,
                                            detalle="Se abrió la caja con el código autorizado.",
                                        )
            finally:
                clear_buffer()

        usuario_actual = obtener_usuario_actual()
        botones_service = BotonesService()

        if usuario_es_nuevo and usuario_id is not None:
            botones_service.otorgar_plantilla_a_usuario_nuevo(usuario_id)

        # ACCIONES queda como global del modulo (estamos dentro de
        # if __name__ == "__main__", no de una funcion) para que un archivo en
        # acciones/ pueda invocar a otro por su nombre via globals()["ACCIONES"],
        # sin duplicar codigo entre botones.
        ACCIONES = cargar_acciones(BASE_DIR)

        bridge = SheetButtonBridge(context, documento, BASE_DIR)

        def construir_botones():
            # Se puede volver a llamar (ej. al cerrar el panel de admin) para
            # reflejar cambios de botones/visibilidad sin reiniciar el
            # sistema: reset_buttons() limpia el estado en memoria y
            # publish_layout() manda a Basic a borrar y recrear los controles
            # en la hoja con la lista actualizada.
            bridge.reset_buttons()

            # Se registra primero para que quede arriba del todo
            # (SheetButtonBridge apila los botones en el mismo orden en que
            # se registran).
            if usuario_actual == ADMIN_RAIZ:
                bridge.add_button("ADMINISTRAR ADMINS", abrir_panel_admin)

            botones_visibles = []
            if usuario_id is not None:
                botones_visibles = botones_service.listar_botones_visibles_para(usuario_id)

            for boton_id, etiqueta, archivo_accion, _orden in botones_visibles:
                modulo = ACCIONES.get(archivo_accion)
                if modulo is None:
                    print(f"[botones] '{etiqueta}' referencia '{archivo_accion}', que no existe en acciones/. Se omite.")
                    continue

                # SheetButtonBridge identifica cada boton por handler.__name__,
                # y todas las lambdas comparten el mismo __name__
                # ("<lambda>") -- sin esto, todos los botones dinamicos
                # colisionan en un solo action_id y se pisan entre si en la hoja.
                def manejador(modulo=modulo):
                    return modulo.ejecutar(globals())
                manejador.__name__ = f"boton_dinamico_{boton_id}"

                bridge.add_button(etiqueta, manejador)

            bridge.publish_layout()

        def abrir_panel_admin():
            from ui.panel_admin import abrir_panel_administracion

            abrir_panel_administracion(context, botones_service, usuario_actual)
            construir_botones()

        bridge.prepare(clear_events=True)
        construir_botones()
        bridge.start()
        atexit.register(bridge.close)

        keyboard.add_hotkey("enter", on_enter)

        # Bucle de control: verifica si el documento sigue vivo
        exc = vigilar_documento(documento)
        print(f"El documento ha sido cerrado o no es accesible: {type(exc)}: {exc}")
        cierre_normal = resolver_salida_del_documento(exc)
        if seguimiento_sesion is not None:
            try:
                seguimiento_sesion.cerrar(
                    exitosa=cierre_normal,
                    detalle=None if cierre_normal else f"{type(exc).__name__}: {exc}",
                )
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
        terminar_libreoffice(desktop)
