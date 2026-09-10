"""Lanza camera_viewer como PROCESO SEPARADO, con su propio interprete de
Python -- nunca el que esta ejecutando este modulo.

Por que: el boton "VER CAMARAS" corre dentro del Python embebido de
LibreOffice. En Linux ese Python viene integrado al paquete de LibreOffice
de cada distro -- instalarle paquetes (PySide6, opencv, numpy...) depende
de la distro y es fragil, a veces imposible sin tocar el sistema. En vez de
pelear con eso, camera_viewer corre en su propio interprete (un venv
normal del proyecto, manejado con pip como cualquier otro), y el boton
unicamente lo lanza como subproceso independiente y sigue de largo -- no
espera a que cierre, no bloquea nada del lado de LibreOffice.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Orden de busqueda dentro de <base_dir>/.venv: pythonw.exe primero en
# Windows (no abre consola detras de la GUI), luego python.exe como
# respaldo, luego las rutas equivalentes de Linux/macOS.
_VENV_PYTHON_CANDIDATES = (
    ("Scripts", "pythonw.exe"),
    ("Scripts", "python.exe"),
    ("bin", "python3"),
    ("bin", "python"),
)

LOG_RUNS_TO_KEEP = 20

# Variables que un Python embebido (LibreOffice, y en general cualquier
# app que embeba su propio interprete) usa para apuntar A SU PROPIA
# instalacion. Si el subproceso las hereda, su interprete (de un venv
# totalmente distinto) intenta resolver la biblioteca estandar ahi en vez
# de en la suya -- el sintoma real visto es "SRE module mismatch" (el _sre
# compilado de un Python choca con el codigo fuente de re/ de otro). Se
# quitan del entorno del hijo, nunca del de este proceso.
_ENV_VARS_TO_STRIP = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE")


def _clean_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for var in _ENV_VARS_TO_STRIP:
        env.pop(var, None)
    return env


def find_python_executable(base_dir: Path) -> Path | None:
    """Busca el interprete del venv del proyecto (<base_dir>/.venv). None
    si no existe -- el llamador decide como avisarlo; nunca debe caer en
    usar sys.executable, que dentro de LibreOffice es el interprete
    equivocado (le faltan todos los paquetes de camera_viewer)."""
    venv_dir = base_dir / ".venv"

    for parts in _VENV_PYTHON_CANDIDATES:
        candidate = venv_dir.joinpath(*parts)
        if candidate.exists():
            return candidate

    return None


def _prepare_log_file(base_dir: Path) -> Path:
    """Un archivo de log nuevo por lanzamiento, igual que
    _activar_log_de_depuracion() en main.py -- necesario porque
    pythonw.exe no tiene consola: si camera_viewer truena al arrancar
    (falta un paquete, error de Qt, lo que sea), sin esto el error
    desaparece por completo y no queda ningun rastro de que algo fallo."""
    logs_dir = base_dir / "logs" / "camera_viewer"
    logs_dir.mkdir(parents=True, exist_ok=True)

    existentes = sorted(logs_dir.glob("run_*.log"))
    for viejo in existentes[: max(0, len(existentes) - (LOG_RUNS_TO_KEEP - 1))]:
        try:
            viejo.unlink()
        except OSError:
            pass

    nombre = datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
    return logs_dir / nombre


def launch_detached(base_dir: Path) -> subprocess.Popen:
    """Lanza 'python -m camera_viewer' en un proceso completamente aparte.
    Devuelve de inmediato (no espera a que la ventana se cierre); su
    stdout/stderr quedan en logs/camera_viewer/run_*.log."""
    python_executable = find_python_executable(base_dir)
    if python_executable is None:
        raise FileNotFoundError(
            f"No se encontro el entorno Python de camera_viewer en {base_dir / '.venv'}. "
            "Crealo con 'python -m venv .venv' y 'pip install -r requirements.txt' "
            "dentro de esa carpeta antes de usar VER CAMARAS."
        )

    log_path = _prepare_log_file(base_dir)
    popen_kwargs: dict = {"cwd": str(base_dir), "stdin": subprocess.DEVNULL, "env": _clean_child_env()}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    with open(log_path, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [str(python_executable), "-m", "camera_viewer"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )

    return process
