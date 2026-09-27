"""Volcado del estado de todos los hilos bajo pedido, para diagnosticar un hilo que se queda
callado sin morir (un error se ve en el log; un hilo colgado, sin excepción, no deja rastro).

2026-09-23: los botones de la hoja dejaron de responder dos veces seguidas, sin ningún error en
el log (el documento seguía funcionando bien: el usuario podía escribir y cerrar normalmente).
Nada murió con una excepción -- lo que sugiere que el hilo de SheetButtonBridge (u otro) se quedó
bloqueado en vez de morir. Esto permite pedirle al proceso, en caliente, que muestre en qué línea
está atascado cada hilo, sin tener que reiniciar ni adivinar."""

import faulthandler
import signal


def activar_volcado_de_hilos(pid, archivo_log):
    """Con el sistema abierto, `kill -SIGUSR1 <pid>` escribe en `archivo_log` la pila de TODOS
    los hilos activos en ese instante -- incluido uno que dejó de responder sin haber muerto.

    Se escribe ahi (el archivo que devuelve activar_log_de_depuracion) y no en sys.stderr: el
    volcado usa el descriptor real del archivo que se le pase en el momento de registrarse, y ese
    descriptor no sigue los reasignos posteriores de sys.stderr (p. ej. el _Tee de
    log_depuracion) -- pasarlo explicito es la unica forma de que quede en el log del run."""
    try:
        faulthandler.register(signal.SIGUSR1, file=archivo_log, all_threads=True)
    except (ValueError, AttributeError) as exc:
        # ValueError: no aplica en el hilo principal si no lo es (no debería pasar aquí).
        # AttributeError: SIGUSR1 no existe en Windows.
        print(f"[diagnostico] No se pudo activar el volcado de hilos: {exc}")
        return

    print(f"[diagnostico] Volcado de hilos listo: si el sistema deja de responder, "
          f"`kill -SIGUSR1 {pid}` escribe aquí en qué línea está atascado cada hilo.")
