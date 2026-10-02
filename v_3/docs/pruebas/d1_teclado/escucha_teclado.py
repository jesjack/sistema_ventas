"""Prueba D1 (V3): escuchar el teclado de un documento de Calc con un XKeyHandler remoto y anotar
la hora de llegada de cada evento, para recalcular los umbrales de is_scan().

Uso: python3 escucha_teclado.py PUERTO ARCHIVO_SALIDA
Se conecta a un soffice de PRUEBAS (nunca al 2002 de producción), abre una hoja nueva y anota
cada keyPressed/keyReleased. No consume las teclas: Calc se comporta normal."""

import sys
import threading
import time

import uno
import unohelper
from com.sun.star.awt import XKeyHandler

PUERTO = int(sys.argv[1])
SALIDA = sys.argv[2]

eventos = []
candado = threading.Lock()


class Escucha(unohelper.Base, XKeyHandler):
    def keyPressed(self, ev):
        t = time.perf_counter_ns()
        with candado:
            eventos.append((t, "P", ev.KeyCode, ev.KeyChar, ev.Modifiers, ev.KeyFunc))
        return False

    def keyReleased(self, ev):
        t = time.perf_counter_ns()
        with candado:
            eventos.append((t, "R", ev.KeyCode, ev.KeyChar, ev.Modifiers, ev.KeyFunc))
        return False

    def disposing(self, ev):
        pass


def conectar():
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(120):
        try:
            ctx = resolver.resolve(f"uno:socket,host=localhost,port={PUERTO};urp;StarOffice.ComponentContext")
            return ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"No se pudo conectar al puerto {PUERTO}")


def main():
    desktop = conectar()
    doc = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    controlador = doc.getCurrentController()
    controlador.addKeyHandler(Escucha())
    frame = controlador.getFrame()
    frame.setTitle("PRUEBA TECLADO V3")
    frame.getContainerWindow().setFocus()

    inicio_ns = time.perf_counter_ns()
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write(f"# inicio {time.strftime('%Y-%m-%d %H:%M:%S')} perf_ns={inicio_ns}\n")
        f.write("# t_ms\ttipo\tKeyCode\tKeyChar\tModifiers\tKeyFunc\n")
        f.flush()
        print("Escuchando. Cierra el documento de prueba para terminar.", flush=True)
        while True:
            time.sleep(0.2)
            with candado:
                pendientes = eventos[:]
                eventos.clear()
            for t, tipo, code, char, mods, func in pendientes:
                f.write(f"{(t - inicio_ns) / 1e6:.3f}\t{tipo}\t{code}\t{char!r}\t{mods}\t{func}\n")
            if pendientes:
                f.flush()
            try:
                _ = doc.Title
            except Exception:
                break
    print("Documento cerrado; fin.", flush=True)


if __name__ == "__main__":
    main()
