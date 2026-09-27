import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Antes de cualquier import local: los de más abajo dependen de esto.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nucleo.config import DEBUG_RUNS_TO_KEEP
from nucleo.diagnostico import activar_volcado_de_hilos
from nucleo.log_depuracion import activar_log_de_depuracion

# Lo antes posible (antes de cualquier otro import), para que incluso un fallo temprano
# (ej. el import de "uno" más abajo) quede capturado en logs/debug/.
archivo_log = activar_log_de_depuracion(BASE_DIR / "logs" / "debug", DEBUG_RUNS_TO_KEEP)
activar_volcado_de_hilos(os.getpid(), archivo_log)

print("Iniciando sistema de ventas...")

try:
    import uno  # noqa: F401
except ImportError:
    print("Warning: 'uno' module not found. Make sure you're running from LibreOffice Python.")
    sys.exit(1)

from rich.traceback import install

from nucleo.arranque import ejecutar

install(show_locals=True)  # Muestra las variables locales al fallar

if __name__ == "__main__":
    ejecutar(BASE_DIR)
