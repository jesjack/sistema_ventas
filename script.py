import os
import sys
import time

import uno
import unohelper
from com.sun.star.awt import Key as UnoKey
from com.sun.star.awt import XKeyHandler

from tpv_module.__module__ import autocompletar_b3

LOG_PATH = "/tmp/tpv_tab_debug.log"


def conectar_a_calc():
    try:
        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_context
        )
        ctx = resolver.resolve(
            "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"
        )
        desktop = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx
        )
        doc = desktop.getCurrentComponent()
        return doc
    except Exception as e:
        with open(os.path.expanduser("~/error_conexion.txt"), "w") as f:
            f.write(f"No se pudo conectar al puerto 2002: {e}")
        sys.exit(1)


def obtener_hoja_tpv(doc):
    for nombre in ("TPV", "tpv"):
        if doc.Sheets.hasByName(nombre):
            return doc.Sheets.getByName(nombre)
    raise ValueError("No existe una hoja llamada TPV o tpv")


def log_tab(msg: str) -> None:
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def iniciar_log() -> None:
    try:
        with open(LOG_PATH, "w") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} log iniciado\n")
    except Exception:
        pass


def es_b3_seleccion_actual(doc) -> bool:
    try:
        seleccion = obtener_seleccion_actual(doc)
        if seleccion is None:
            log_tab("Seleccion actual no disponible")
            return False

        hoja = doc.getCurrentController().getActiveSheet()
        if hoja.Name.strip().lower() != "tpv":
            log_tab(f"Hoja activa ignorada: {hoja.Name}")
            return False

        if seleccion.supportsService("com.sun.star.table.Cell"):
            row = int(seleccion.CellAddress.Row)
            col = int(seleccion.CellAddress.Column)
            log_tab(f"Seleccion celda row={row} col={col}")
            return row == 2 and col == 1

        if seleccion.supportsService("com.sun.star.sheet.SheetCellRange"):
            addr = seleccion.getRangeAddress()
            log_tab(
                "Seleccion rango "
                f"sr={addr.StartRow} er={addr.EndRow} sc={addr.StartColumn} ec={addr.EndColumn}"
            )
            return (
                int(addr.StartRow) == 2
                and int(addr.EndRow) == 2
                and int(addr.StartColumn) == 1
                and int(addr.EndColumn) == 1
            )

        return False
    except Exception as e:
        log_tab(f"Error evaluando B3: {e}")
        return False


def obtener_seleccion_actual(doc):
    try:
        return doc.getCurrentSelection()
    except Exception:
        try:
            return doc.getCurrentController().getCurrentSelection()
        except Exception:
            return None


def aceptar_edicion_activa(doc) -> bool:
    try:
        local_context = uno.getComponentContext()
        dispatcher = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", local_context
        )
        frame = doc.getCurrentController().getFrame()
        dispatcher.executeDispatch(frame, ".uno:AcceptFormula", "", 0, tuple())
        log_tab("Edicion activa aceptada con .uno:AcceptFormula")
        return True
    except Exception as e:
        log_tab(f"No se pudo aceptar la edicion activa: {e}")
        return False


class CalcKeyHandler(unohelper.Base, XKeyHandler):
    def __init__(self, doc, hoja, password: str):
        self.doc = doc
        self.hoja = hoja
        self.password = password

    def keyPressed(self, event):
        if event.KeyCode != UnoKey.TAB:
            return False

        log_tab("TAB detectado por XKeyHandler")

        if es_b3_seleccion_actual(self.doc):
            try:
                aceptar_edicion_activa(self.doc)
                time.sleep(0.05)
                log_tab("TAB en B3: ejecutando autocompletar_b3")
                autocompletar_b3(self.hoja, doc=self.doc, password=self.password)
                log_tab("TAB en B3: autocompletar_b3 finalizado")
            except Exception as e:
                with open(os.path.expanduser("~/error_autocompletado.txt"), "w") as f:
                    f.write(f"Error en autocompletado: {e}")
                log_tab(f"Error en autocompletado: {e}")
            return True

        log_tab("TAB detectado fuera de B3")
        return False

    def keyReleased(self, event):
        return False

    def disposing(self, event):
        return None


def loop_principal(doc, hoja, password: str) -> None:
    celda_a1 = hoja.getCellRangeByName("A1")
    rojo = 0xFF0000
    verde = 0x00FF00
    color_actual = rojo
    ultimo_blink = 0.0
    controller = doc.getCurrentController()
    key_handler = CalcKeyHandler(doc, hoja, password)

    iniciar_log()
    controller.addKeyHandler(key_handler)

    print("Loop activo: A1 parpadea y TAB se detecta via UNO. Ctrl+C para detener.")
    log_tab("Script iniciado en modo loop_principal")

    try:
        while True:
            ahora = time.time()

            if ahora - ultimo_blink >= 1.0:
                try:
                    if hoja.isProtected():
                        hoja.unprotect(password)

                    celda_a1.CellBackColor = color_actual
                    color_actual = verde if color_actual == rojo else rojo
                finally:
                    if not hoja.isProtected():
                        hoja.protect(password)

                ultimo_blink = ahora

            time.sleep(0.05)
    finally:
        try:
            controller.removeKeyHandler(key_handler)
        except Exception:
            pass


def main() -> None:
    doc = conectar_a_calc()
    hoja = obtener_hoja_tpv(doc)
    password = os.getenv("TPV_SHEET_PASSWORD", "")

    comando = sys.argv[1] if len(sys.argv) > 1 else "loop"

    if comando == "loop":
        loop_principal(doc, hoja, password)
        return

    if comando == "autocomplete-b3":
        autocompletar_b3(hoja, doc=doc, password=password)
        return

    if comando != "blink-a1":
        print("Uso: python script.py [loop|blink-a1|autocomplete-b3]")
        sys.exit(2)

    loop_principal(doc, hoja, password)


if __name__ == "__main__":
    main()

