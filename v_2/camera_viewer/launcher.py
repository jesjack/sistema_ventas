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
_ROOT_XDG_VARS = ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")

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


def _drop_privileges_kwargs() -> dict:
    """Si este proceso (main.py) corre como root porque se lanzo con sudo
    (ver libreofficeModules/Module1.bas), camera_viewer no tiene por que
    heredar eso: solo hace peticiones de red salientes (RTSP/HTTP-CGI al
    DVR) y renderiza una GUI, nada que requiera privilegios. Usa las mismas
    variables que sudo expone (SUDO_UID/SUDO_GID/SUDO_USER) -- las mismas
    que ya lee TPV_UsuarioActual() en el modulo de Basic -- para arrancar
    el subproceso como el usuario real detras del sudo. Devuelve un dict
    vacio (sin tocar nada) si no aplica: no es root, no es POSIX, o no hay
    rastro de sudo en el entorno (main.py corriendo directo, sin sudo)."""
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
    # los suyos. Encontrado 2026-09-24: es la causa real de que "VER CAMARAS" no funcionara
    # para otro usuario del grupo -- sin su membresía real (p. ej. tpv_yaeli), ese usuario no
    # tenia NINGUN permiso sobre los archivos compartidos que otro ya habia creado (candados,
    # la carpeta de descargas, el archivo de grabaciones; ver shared_paths.py), ni podia el
    # propio proceso arreglarlo (chown/chmod a un grupo del que el kernel no lo cree miembro).
    try:
        kwargs["extra_groups"] = os.getgrouplist(sudo_user, gid)
    except (KeyError, OSError):
        pass
    return kwargs


def _target_user_env() -> dict[str, str]:
    """Variables de entorno del usuario al que se baja el proceso (ver _drop_privileges_kwargs).
    Bajar el uid/gid NO cambia el entorno: el hijo seguía con HOME=/root, USER=root, y toda
    ruta "del usuario" (la carpeta de vídeos, la configuración de Qt) apuntaba a /root."""
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
    equivocado (le faltan todos los paquetes de camera_viewer)."""
    venv_dir = base_dir / ".venv"

    for parts in _VENV_PYTHON_CANDIDATES:
        candidate = venv_dir.joinpath(*parts)
        if candidate.exists():
            return candidate

    return None


def _prepare_log_file(base_dir: Path, prefix: str = "run") -> Path:
    """Un archivo de log nuevo por lanzamiento, igual que
    _activar_log_de_depuracion() en main.py -- necesario porque
    pythonw.exe no tiene consola: si camera_viewer truena al arrancar
    (falta un paquete, error de Qt, lo que sea), sin esto el error
    desaparece por completo y no queda ningun rastro de que algo fallo.
    `prefix` distingue los logs de la ventana (`run_*`) de los del
    archivador (`archiver_run_*`, ver launch_archiver): cada uno cuida
    solo los suyos al podar, sin pisar la retención del otro."""
    logs_dir = base_dir / "logs" / "camera_viewer"
    logs_dir.mkdir(parents=True, exist_ok=True)

    existentes = sorted(logs_dir.glob(f"{prefix}_*.log"))
    for viejo in existentes[: max(0, len(existentes) - (LOG_RUNS_TO_KEEP - 1))]:
        try:
            viejo.unlink()
        except OSError:
            pass

    nombre = datetime.now().strftime(f"{prefix}_%Y%m%d_%H%M%S.log")
    return logs_dir / nombre


def _child_popen_kwargs(base_dir: Path) -> dict:
    """Los kwargs de subprocess.Popen comunes a cualquier hijo de camera_viewer (la ventana,
    el archivador...): carpeta de trabajo, entorno limpio (ver _clean_child_env) y, si este
    proceso es root por sudo, bajado al usuario real de atrás (ver _drop_privileges_kwargs)."""
    popen_kwargs: dict = {"cwd": str(base_dir), "stdin": subprocess.DEVNULL, "env": _clean_child_env()}
    popen_kwargs.update(_drop_privileges_kwargs())
    if "user" in popen_kwargs:
        popen_kwargs["env"].update(_target_user_env())
        for var in _ROOT_XDG_VARS:  # rutas XDG heredadas de root: que las derive de su HOME
            popen_kwargs["env"].pop(var, None)
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return popen_kwargs


def _launch_module(base_dir: Path, module: str, log_prefix: str, hint: str) -> subprocess.Popen:
    python_executable = find_python_executable(base_dir)
    if python_executable is None:
        raise FileNotFoundError(
            f"No se encontró el entorno Python de camera_viewer en {base_dir / '.venv'}. "
            f"Créalo con 'python -m venv .venv' y 'pip install -r requirements.txt' "
            f"dentro de esa carpeta antes de {hint}."
        )

    log_path = _prepare_log_file(base_dir, prefix=log_prefix)
    with open(log_path, "a", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [str(python_executable), "-m", module],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **_child_popen_kwargs(base_dir),
        )


def launch_detached(base_dir: Path) -> subprocess.Popen:
    """Lanza 'python -m camera_viewer' en un proceso completamente aparte.
    Devuelve de inmediato (no espera a que la ventana se cierre); su
    stdout/stderr quedan en logs/camera_viewer/run_*.log."""
    return _launch_module(base_dir, "camera_viewer", "run", "usar VER CAMARAS")


def launch_archiver(base_dir: Path) -> subprocess.Popen:
    """Lanza 'python -m camera_viewer.archiver' -- el archivador pasivo (ver archiver.py) que
    copia a la PC lo más viejo que el DVR tenga, antes de que se sobrescriba. Pensado para
    llamarse una vez por arranque del POS (ver nucleo/arranque.py); no hay que cuidarse de
    lanzarlo dos veces, archiver.py tiene su propio candado de instancia única
    (share/runtime/archiver.lock) -- una segunda instancia lo nota, avisa y termina sola.
    Su stdout/stderr quedan en logs/camera_viewer/archiver_run_*.log."""
    return _launch_module(base_dir, "camera_viewer.archiver", "archiver_run", "que el archivador pueda correr")
