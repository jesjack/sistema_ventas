"""Espejo de stdout/stderr a un archivo por ejecución. No importa nada del proyecto, para poder
activarse antes que cualquier otro import y capturar hasta un fallo temprano."""

import atexit
import re
import sys
from datetime import datetime


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


def activar_log_de_depuracion(logs_dir, runs_to_keep=20):
    """Espeja todo stdout/stderr de este proceso (prints, tracebacks
    incluyendo el que arma rich.traceback.install) a un archivo nuevo por
    ejecucion en logs/debug/, ademas de la consola -- para poder diagnosticar
    un error que la consola cerro antes de que alguien alcanzara a copiarlo.
    Se llama a esto lo antes posible (antes de cualquier otro import), para
    que incluso un fallo temprano (ej. el import de "uno" mas abajo) quede
    capturado.

    Se retienen solo las ultimas runs_to_keep ejecuciones (el nombre de
    archivo trae timestamp, asi que ordenar por nombre ya da el mas
    reciente) -- suficiente para no perder evidencia si el sistema se
    reabrio una o dos veces entre que ocurrio el error y se reporta, sin
    crecer sin limite para siempre.

    Devuelve el archivo de este run (sin el filtro de color), por si algo mas
    -- ver nucleo.diagnostico -- necesita escribir ahi directamente en vez de
    por sys.stdout/stderr (p. ej. faulthandler.register() usa el descriptor de
    archivo real de lo que le pasen, y ese descriptor NO sigue a sys.stderr si
    algo lo reasigna despues).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)

    existentes = sorted(logs_dir.glob("run_*.log"))
    for viejo in existentes[: max(0, len(existentes) - (runs_to_keep - 1))]:
        try:
            viejo.unlink()
        except OSError:
            pass

    nombre = datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
    archivo = open(logs_dir / nombre, "a", encoding="utf-8", buffering=1)
    # Se registra primero para que, por el orden inverso de atexit, el archivo
    # se cierre al final, después de los demás cierres que aún impriman algo.
    atexit.register(archivo.close)
    archivo_sin_color = _SinColor(archivo)
    sys.stdout = _Tee(sys.stdout, archivo_sin_color)
    sys.stderr = _Tee(sys.stderr, archivo_sin_color)
    return archivo
