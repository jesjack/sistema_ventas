"""Lanza admin_botones como PROCESO SEPARADO, con su propio interprete de
Python -- nunca el que esta ejecutando este modulo.

Por que: el boton "ADMINISTRAR ADMINS" corre dentro del Python embebido de
LibreOffice. En Linux ese Python viene integrado al paquete de LibreOffice
de cada distro -- instalarle paquetes (PySide6...) depende de la distro y es
fragil, a veces imposible sin tocar el sistema. En vez de pelear con eso,
admin_botones corre en su propio interprete (el venv normal del proyecto,
el mismo que ya usa camera_viewer), y el boton unicamente lo lanza como
subproceso independiente y sigue de largo -- no espera a que cierre, no
bloquea nada del lado de LibreOffice.

Es una COPIA independiente del mismo patron que ya usa camera_viewer/launcher.py
(no un import de ahi): hay otra instancia trabajando en camera_viewer, y esto
evita depender de ese modulo o arriesgar un conflicto con sus cambios.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from admin_botones.instancia_unica import hay_instancia_activa

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
_ROOT_XDG_VARS = ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")

# Variables que un Python embebido (LibreOffice, y en general cualquier
# app que embeba su propio interprete) usa para apuntar A SU PROPIA
# instalacion. Si el subproceso las hereda, su interprete (de un venv
# totalmente distinto) intenta resolver la biblioteca estandar ahi en vez
# de en la suya. Se quitan del entorno del hijo, nunca del de este proceso.
_ENV_VARS_TO_STRIP = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE")


def _clean_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for var in _ENV_VARS_TO_STRIP:
        env.pop(var, None)
    # Sin esto, stdout queda con buffer de bloque completo por estar redirigido a un archivo
    # (no una terminal): si el proceso muere de golpe todo lo impreso desde el ultimo flush se
    # pierde, y el log queda vacio aunque el proceso si haya hecho trabajo real.
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _drop_privileges_kwargs() -> dict:
    """Si este proceso (main.py) corre como root porque se lanzo con sudo
    (ver libreofficeModules/Module1.bas), admin_botones no tiene por que
    heredar eso: solo lee/escribe ventas.db (services/base_datos.py) y
    renderiza una GUI, nada que requiera privilegios. Usa las mismas
    variables que sudo expone (SUDO_UID/SUDO_GID/SUDO_USER) para arrancar
    el subproceso como el usuario real detras del sudo. Devuelve un dict
    vacio (sin tocar nada) si no aplica."""
    if os.name != "posix":
        return {}
    if os.geteuid() != 0:
        return {}

    sudo_user = os.environ.get("SUDO_USER")
    sudo_gid = os.environ.get("SUDO_GID")
    if not sudo_user or not sudo_gid:
        return {}

    try:
        gid = int(sudo_gid)
    except ValueError:
        return {}

    kwargs: dict = {"user": sudo_user, "group": gid}
    # Sin esto, subprocess.Popen NUNCA llama a setgroups() en el hijo (solo lo hace si se le
    # pasa extra_groups) -- el proceso bajado se queda con los grupos SUPLEMENTARIOS de root
    # (typicamente ninguno util), no los del usuario real, aunque uid/gid principal ya sean
    # los suyos (ver el mismo hallazgo, documentado, en camera_viewer/launcher.py).
    try:
        kwargs["extra_groups"] = os.getgrouplist(sudo_user, gid)
    except (KeyError, OSError):
        pass
    return kwargs


def _target_user_env() -> dict[str, str]:
    """Variables de entorno del usuario al que se baja el proceso (ver _drop_privileges_kwargs).
    Bajar el uid/gid NO cambia el entorno: el hijo seguiria con HOME=/root, USER=root."""
    sudo_user = os.environ.get("SUDO_USER")
    if not sudo_user:
        return {}
    try:
        import pwd

        entry = pwd.getpwnam(sudo_user)
    except (ImportError, KeyError):
        return {}
    return {"HOME": entry.pw_dir, "USER": entry.pw_name, "LOGNAME": entry.pw_name}


def find_python_executable(base_dir: Path) -> Path | None:
    """Busca el interprete del venv del proyecto (<base_dir>/.venv). None
    si no existe -- el llamador decide como avisarlo; nunca debe caer en
    usar sys.executable, que dentro de LibreOffice es el interprete
    equivocado (le faltan todos los paquetes de admin_botones)."""
    venv_dir = base_dir / ".venv"

    for parts in _VENV_PYTHON_CANDIDATES:
        candidate = venv_dir.joinpath(*parts)
        if candidate.exists():
            return candidate

    return None


def _prepare_log_file(base_dir: Path) -> Path:
    """Un archivo de log nuevo por lanzamiento -- necesario porque pythonw.exe no tiene consola:
    si admin_botones truena al arrancar, sin esto el error desaparece por completo."""
    logs_dir = base_dir / "logs" / "admin_botones"
    logs_dir.mkdir(parents=True, exist_ok=True)

    existentes = sorted(logs_dir.glob("run_*.log"))
    for viejo in existentes[: max(0, len(existentes) - (LOG_RUNS_TO_KEEP - 1))]:
        try:
            viejo.unlink()
        except OSError:
            pass

    nombre = datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
    return logs_dir / nombre


def launch_detached(base_dir: Path) -> subprocess.Popen | None:
    """Lanza 'python -m admin_botones <base_dir>' en un proceso completamente aparte. Devuelve
    de inmediato (no espera a que la ventana se cierre); su stdout/stderr quedan en
    logs/admin_botones/run_*.log.

    Si ya hay una ventana abierta, no lanza una segunda: le manda un ping (ver
    instancia_unica.py) para que se traiga sola al frente, y devuelve None."""
    if hay_instancia_activa(base_dir):
        return None

    python_executable = find_python_executable(base_dir)
    if python_executable is None:
        raise FileNotFoundError(
            f"No se encontró el entorno Python en {base_dir / '.venv'}. "
            f"Créalo con 'python -m venv .venv' y 'pip install -r requirements.txt' "
            f"dentro de esa carpeta antes de usar ADMINISTRAR ADMINS."
        )

    log_path = _prepare_log_file(base_dir)
    popen_kwargs: dict = {
        "cwd": str(base_dir),
        "stdin": subprocess.DEVNULL,
        "env": _clean_child_env(),
    }
    popen_kwargs.update(_drop_privileges_kwargs())
    if "user" in popen_kwargs:
        popen_kwargs["env"].update(_target_user_env())
        for var in _ROOT_XDG_VARS:
            popen_kwargs["env"].pop(var, None)
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    with open(log_path, "a", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [str(python_executable), "-m", "admin_botones", str(base_dir)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
