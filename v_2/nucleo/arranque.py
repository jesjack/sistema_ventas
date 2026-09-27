"""Arranque del punto de venta: conecta con LibreOffice, arma los servicios, las tablas y los
botones, y se queda vigilando el documento hasta que se cierre.

main.py solo prepara el entorno (rutas, log, `uno`) y llama a `ejecutar`."""

import atexit
import sys
from datetime import datetime

import keyboard
import uno

from calc.calc_focus import enfocar_celda_sin_azul, registrar_seguimiento_foco_calc
from calc.calc_window_focus import es_libreoffice_calc_enfocado
from calc.sheet_admin import SheetAdmin
from dialogs.aviso_error import mostrar_aviso_error
from dialogs.cobro_uno import solicitar_monto_cliente
from dialogs.codigo_autorizacion import solicitar_codigo
from dialogs.precio_venta import solicitar_precio_venta
from hardware.ticket_printer import imprimir_ticket_venta
from nucleo.botones import BotonesDeLaHoja
from nucleo.caja import abrir_caja
from nucleo.ciclo_documento import (
    obtener_documento_calc,
    resolver_salida_del_documento,
    terminar_libreoffice,
    vigilar_documento,
)
from nucleo.config import PUERTO_LIBREOFFICE
from nucleo.contexto import Contexto
from nucleo.controlador_venta import ControladorVenta
from nucleo.tablas import preparar_tablas
from services import scanner_detector
from services.accion_registry import cargar_acciones
from services.botones_service import BotonesService
from services.button_bridge import SheetButtonBridge
from services.catalogo_service import CatalogoService
from services.codigos_barras_service import CodigosBarrasService
from services.identidad import obtener_usuario_actual
from services.instancia_unica import asegurar_instancia_unica
from services.modo_sistema import escribir_modo, leer_modo, solicitar_relanzamiento
from services.seguimiento_sesion import SeguimientoSesionSistema
from services.usuarios_service import UsuariosService
from services.ventas_service import VentasService
from table_modules import attach_existing
from table_modules.table_manager import TableManager
from ui.autocompletado_producto import AutocompletadoProductoHandler


def conectar_libreoffice(puerto):
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_context)
    context = resolver.resolve(f"uno:socket,host=localhost,port={puerto};urp;StarOffice.ComponentContext")
    desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    return context, desktop


def _iniciar_archivador_de_camaras(base_dir):
    """Arranca el archivador pasivo de camera_viewer (ver camera_viewer/archiver.py) mientras
    el POS esté abierto: copia a la PC lo más viejo que el DVR tenga, antes de que el DVR mismo
    lo sobrescriba. Import LOCAL a propósito (no arriba del archivo, junto a los demás): el
    paquete camera_viewer importa OpenCV/PySide6, que no están instalados en el Python embebido
    de LibreOffice que corre este módulo -- camera_viewer.launcher sí (solo biblioteca estándar)
    y lanza el archivador como proceso APARTE, en el venv propio de camera_viewer (igual que
    "VER CAMARAS", ver acciones/ver_camaras.py). No hay que evitar llamarlo más de una vez:
    archiver.py tiene su propio candado de instancia única."""
    from camera_viewer.launcher import launch_archiver

    try:
        proceso = launch_archiver(base_dir)
    except FileNotFoundError as exc:
        print(f"[archivador] {exc}")
        return None
    print(f"[archivador] camera_viewer.archiver lanzado (pid={proceso.pid}); su log queda en logs/camera_viewer/")
    return proceso


def _detener_archivador_de_camaras(proceso):
    """Cierre ordenado (ver la nota de SIGTERM en archiver.py): le da unos segundos a que
    termine lo que tenga a medias antes de insistir."""
    try:
        proceso.terminate()
        proceso.wait(timeout=5)
    except Exception:
        try:
            proceso.kill()
        except Exception:
            pass


def ejecutar(base_dir):
    # Solo un usuario a la vez: si otro tiene el puerto de LibreOffice, se le
    # cierra su sistema y este proceso sale para que open_system.sh relance
    # (ver services/instancia_unica.py).
    if not asegurar_instancia_unica():
        sys.exit(0)

    proceso_archivador = _iniciar_archivador_de_camaras(base_dir)
    if proceso_archivador is not None:
        atexit.register(_detener_archivador_de_camaras, proceso_archivador)

    context, desktop = conectar_libreoffice(PUERTO_LIBREOFFICE)
    documento = obtener_documento_calc(desktop)
    if documento is None:
        print("No se encontro un documento de Calc abierto.")
        sys.exit(1)

    hoja = documento.getSheets().getByIndex(0)
    sheet_admin = SheetAdmin(hoja, document=documento)
    controlador = documento.getCurrentController()
    registrar_seguimiento_foco_calc(documento)

    modo_info = leer_modo()
    if modo_info.get("modo", "normal") == "ventas_dia":
        _modo_ventas_dia(base_dir, context, desktop, documento, hoja, sheet_admin, modo_info)
    else:
        _modo_normal(base_dir, context, desktop, documento, hoja, sheet_admin, controlador)


def _modo_ventas_dia(base_dir, context, desktop, documento, hoja, sheet_admin, modo_info):
    # ---- Flujo de solo lectura: mostrar las ventas de una fecha, con un
    # unico boton para regresar al sistema principal. prebake_ventas.py ya
    # horneo la tabla unica "VENTAS DEL DIA {fecha}" antes de que soffice
    # abriera el archivo -- aqui solo nos enganchamos a lo ya renderizado,
    # igual que hace el flujo normal cuando detecta pre-horneado.
    fecha = modo_info.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    ventas_rows_now = VentasService().obtener_ventas(fecha=fecha)

    with sheet_admin.temporary_unlock():
        attach_existing(
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

    bridge = SheetButtonBridge(context, documento, base_dir)
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


def _registrar_usuario(usuarios, context):
    """Sincroniza los usuarios con el sistema operativo y registra al actual.
    Devuelve (usuario_id, es_nuevo); usuario_id es None si la base no responde."""
    # Se resuelve aqui afuera (no adentro de SeguimientoSesionSistema)
    # para que la visibilidad de botones nunca dependa de que el hilo de
    # latido de sesion arranque bien -- si eso falla mas abajo, igual
    # queremos poder armar los botones de este usuario.
    try:
        desactivados = usuarios.sincronizar_usuarios_con_sistema()
        if desactivados:
            print(f"[usuarios] {desactivados} usuario(s) cambiaron de estado al sincronizar con el sistema.")
    except Exception as exc:
        print(f"[usuarios] No se pudo sincronizar la lista de usuarios: {exc}")

    # Si la base no responde aquí, el punto de venta debe arrancar de todos
    # modos (Enter/escaneo siguen funcionando); sin usuario_id solo se
    # pierden los botones por usuario y el seguimiento de sesión.
    try:
        return usuarios.asegurar_usuario_sistema()
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
        return None, False


def _modo_normal(base_dir, context, desktop, documento, hoja, sheet_admin, controlador):
    ventas_service = VentasService()
    usuarios = UsuariosService()
    catalogo = CatalogoService()
    codigos_barras = CodigosBarrasService()
    table_manager = TableManager(
        ventas_service,
        cobro_provider=lambda total: solicitar_monto_cliente(total, context),
        imprimir_ticket=imprimir_ticket_venta,
    )

    usuario_id, usuario_es_nuevo = _registrar_usuario(usuarios, context)

    seguimiento_sesion = None
    if usuario_id is not None:
        try:
            seguimiento_sesion = SeguimientoSesionSistema(usuarios, usuario_id)
        except Exception as exc:
            print(f"No se pudo iniciar el seguimiento de usuario: {exc}")
        else:
            atexit.register(seguimiento_sesion.cerrar)

    # Es una consulta sqlite local barata.
    ruta_ods = base_dir / "share" / "main.ods"
    tabla_entrada, cart, ventas = preparar_tablas(
        hoja, sheet_admin, table_manager, ventas_service.obtener_ventas(), ruta_ods=ruta_ods
    )

    autocompletado_handler = AutocompletadoProductoHandler(
        context, documento, hoja, tabla_entrada, catalogo, sheet_admin,
    )
    controlador.addKeyHandler(autocompletado_handler)

    botones_service = BotonesService()
    if usuario_es_nuevo and usuario_id is not None:
        botones_service.otorgar_plantilla_a_usuario_nuevo(usuario_id)

    ctx = Contexto(
        base_dir=base_dir,
        context=context,
        desktop=desktop,
        documento=documento,
        hoja=hoja,
        sheet_admin=sheet_admin,
        table_manager=table_manager,
        tabla_entrada=tabla_entrada,
        cart=cart,
        ventas=ventas,
        catalogo=catalogo,
        codigos_barras=codigos_barras,
        autocompletado_handler=autocompletado_handler,
        acciones=cargar_acciones(base_dir),
    )

    venta = ControladorVenta(
        ctx,
        escaner=scanner_detector,
        calc_esta_enfocado=es_libreoffice_calc_enfocado,
        enfocar_celda=enfocar_celda_sin_azul,
        pedir_precio=solicitar_precio_venta,
        pedir_codigo=solicitar_codigo,
        abrir_caja=abrir_caja,
    )

    bridge = SheetButtonBridge(context, documento, base_dir)
    botones = BotonesDeLaHoja(ctx, bridge, botones_service, usuario_id, obtener_usuario_actual())
    bridge.prepare(clear_events=True)
    botones.construir()
    bridge.start()
    atexit.register(bridge.close)

    keyboard.add_hotkey("enter", venta.on_enter)

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
