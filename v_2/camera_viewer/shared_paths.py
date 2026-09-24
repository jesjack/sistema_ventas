from __future__ import annotations

import grp
import os
import shutil
import subprocess
from pathlib import Path

# Los archivos de trabajo de camera_viewer (candados, la clave del servicio, la carpeta de
# descargas temporales y, mas adelante, el archivo local de grabaciones) viven bajo share/ --
# la misma carpeta compartida que ya usa el POS (ver v_2/share/), en vez de runtime/ (que
# queda a nombre de quien lanzo la app por primera vez). Esto es lo que hace falta para que
# CUALQUIER usuario del grupo SHARE_GROUP pueda correr la app: cada usuario del negocio
# (nancy, ruby...) tiene su propia cuenta del sistema, y todas comparten ese grupo.
#
# Dos piezas resuelven el problema junto con esto:
#   - apply_shared_umask(): cada punto de entrada (camera_viewer, download_service, el futuro
#     archiver) la llama una vez al arrancar, para que TODO archivo o carpeta que ese proceso
#     cree quede escribible por el grupo (no solo por quien lo creo), sin tener que acordarse
#     de chequearlo en cada sitio del codigo que escribe algo.
#   - ensure_shared_root(): crea (o adopta) una carpeta raiz compartida, a nombre del grupo y
#     con el bit setgid -- asi todo lo que se cree DENTRO (incluso por otro usuario) hereda ese
#     mismo grupo automaticamente, sin tener que tocar cada subcarpeta una por una.

SHARE_GROUP = "tpv_yaeli"
SHARE_DIR = Path(__file__).resolve().parent.parent / "share"
SHARE_RUNTIME_DIR = SHARE_DIR / "runtime"
# El archivo local de grabaciones (archiver.py). Definida aquí (no en archiver.py) para que
# download_manager.py pueda leerla sin un import circular: archiver.py ya depende de
# download_client -> download_service -> download_manager para descargar del DVR.
ARCHIVE_DIR = SHARE_DIR / "archivo_camaras"

# rwx para el dueño y el grupo, nada para el resto -- with SUID/SGID: el bit setgid (primer
# digito) hace que lo que se cree ADENTRO herede este mismo grupo, no el del usuario que lo crea.
SHARED_DIR_MODE = 0o2770


def apply_shared_umask() -> None:
    """Que todo lo que este proceso cree en share/ (archivos Y carpetas) quede escribible por
    el grupo por construccion. Se llama UNA vez, apenas arranca el proceso -- antes de crear
    cualquier candado, base de datos o carpeta de trabajo. No hace nada en Windows (no tiene
    umask de este estilo; ahi la app la usa un solo usuario de todos modos)."""
    if os.name == "posix":
        os.umask(0o007)


def ensure_shared_root(path: Path, group: str = SHARE_GROUP) -> None:
    """Crea `path` (y las que falten arriba) lista para que cualquier usuario del grupo
    `group` pueda escribir dentro, incluso si otro usuario la creo primero. Nunca falla por
    esto -- si no se puede cambiar el dueño o los permisos (p. ej. ya es de otro usuario y
    este proceso no tiene privilegios), sigue con lo que haya: es una carpeta de trabajo, no
    algo de lo que dependa la correctitud, solo la comodidad multiusuario."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "posix":
        return
    try:
        os.chmod(path, SHARED_DIR_MODE)
    except OSError:
        pass
    try:
        os.chown(path, -1, grp.getgrnam(group).gr_gid)
    except (OSError, KeyError):
        pass
    _strip_inherited_acl(path)


def _strip_inherited_acl(path: Path) -> None:
    """share/ (la carpeta del POS) trae una ACL por defecto heredable de "rwx para cualquiera"
    (para compartirla por Samba) -- sin esto, TODO lo que se cree DENTRO de una carpeta nueva
    aquí abajo hereda esa misma ACL sin importar el chmod de arriba ni el umask del proceso, y
    quedaría legible/escribible por cualquier usuario del sistema, no solo por el grupo. `setfacl
    -b` la quita (vuelve a los permisos clásicos de Unix, los que sí respetan chmod/umask desde
    ahí en adelante); si `setfacl` no está instalado, sigue sin ella -- ver el aviso en NOTAS.md."""
    if shutil.which("setfacl") is None:
        return
    try:
        subprocess.run(["setfacl", "-b", str(path)], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
