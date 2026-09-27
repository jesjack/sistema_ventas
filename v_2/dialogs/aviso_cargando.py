"""Aviso SIN botones que se cierra solo: para una espera cortita (p. ej. mientras un subproceso
propio termina de arrancar su ventana) sin que el usuario tenga que hacer nada para cerrarlo, y
sin bloquear el resto del sistema (a diferencia de mostrar_y_cerrar, no hace dialog.execute())."""

import threading

from dialogs._base import ConstructorDialogo

DURACION_POR_DEFECTO = 1.6


def _crear_dialogo(uno_context, titulo, mensaje):
    c = ConstructorDialogo(uno_context, titulo, 220, 56)
    c.etiqueta("lblMensaje", 10, 18, 200, 24, mensaje, multilinea=True)
    return c.crear()


class AvisoTemporal:
    """Lo que devuelve mostrar_aviso_temporal: `cerrar()` lo quita antes de tiempo (p. ej. si lo
    que se esperaba falló y hay que mostrar un error en su lugar en vez de dejarlo desaparecer
    solo). Cerrarlo dos veces (el temporizador automático y una llamada a mano) no hace nada raro:
    solo la primera vez de verdad lo cierra."""

    def __init__(self, dialog, duracion_segundos: float) -> None:
        self._dialog = dialog
        self._lock = threading.Lock()
        self._cerrado = False
        self._temporizador = threading.Timer(duracion_segundos, self.cerrar)
        self._temporizador.daemon = True
        self._temporizador.start()

    def cerrar(self) -> None:
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
        self._temporizador.cancel()
        try:
            self._dialog.setVisible(False)
            self._dialog.dispose()
        except Exception:
            pass  # la ventana de LibreOffice ya pudo haberse cerrado de por sí

    @property
    def cerrado(self) -> bool:
        """Para quien vigila algo en un hilo aparte (ver acciones/ver_camaras.py): si esto ya
        se cerró (a mano, o porque se agotó `duracion_segundos`), no hace falta seguir vigilando."""
        with self._lock:
            return self._cerrado


def mostrar_aviso_temporal(uno_context, mensaje, titulo="Aviso", duracion_segundos=DURACION_POR_DEFECTO):
    """Muestra `mensaje` de inmediato (sin bloquear, a diferencia de mostrar_y_cerrar) y lo
    cierra solo tras `duracion_segundos`. Devuelve el AvisoTemporal para poder cerrarlo antes,
    a mano, si hiciera falta."""
    dialog = _crear_dialogo(uno_context, titulo, mensaje)
    dialog.setVisible(True)
    return AvisoTemporal(dialog, duracion_segundos)
