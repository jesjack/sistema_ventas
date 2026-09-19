from __future__ import annotations

import getpass
import os

# Usuario ficticio en usuarios_sistema (nunca se loguea de verdad con este
# nombre) cuyos permisos de boton_visibilidad sirven de plantilla: al primer
# login de un usuario real nuevo, se le copian los botones que tenga
# otorgados este usuario -- ver BotonesService.otorgar_plantilla_a_usuario_nuevo.
USUARIO_PLANTILLA = "__default__"


def usuario_existe_en_sistema(nombre_usuario):
    # True/False si se pudo comprobar contra las cuentas del sistema operativo;
    # None si no se pudo (en ese caso nadie debe darse de baja por eso).
    nombre = str(nombre_usuario).strip()
    if not nombre:
        return False

    if os.name == "nt":
        return _usuario_existe_windows(nombre)

    try:
        import pwd
    except ImportError:
        return None

    try:
        pwd.getpwnam(nombre)
        return True
    except KeyError:
        pass
    except Exception:
        return None

    # Los nombres en la BD se guardan en minusculas; en el sistema podrian
    # tener otra capitalizacion.
    try:
        return any(entrada.pw_name.lower() == nombre.lower() for entrada in pwd.getpwall())
    except Exception:
        return None


def _usuario_existe_windows(nombre):
    import subprocess

    try:
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-LocalUser | Select-Object -ExpandProperty Name"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return None

    if resultado.returncode != 0:
        return None

    nombres = {linea.strip().lower() for linea in resultado.stdout.splitlines() if linea.strip()}
    if not nombres:
        return None

    return nombre.lower() in nombres


def obtener_usuario_actual():
    # main.py se lanza con sudo en produccion, asi que un getpass.getuser()
    # o os.getlogin() a secas devuelve "root" -- hay que revisar SUDO_USER
    # (o PKEXEC_UID) primero para llegar al usuario real detras del sudo.
    for clave in ("SUDO_USER", "PKEXEC_UID"):
        valor = os.environ.get(clave)
        if not valor:
            continue

        if clave == "PKEXEC_UID":
            try:
                import pwd

                valor = pwd.getpwuid(int(valor)).pw_name
            except Exception:
                continue

        valor = str(valor).strip()
        if valor and valor.lower() != "root":
            return valor.lower()

    for obtenedor in (getpass.getuser, os.getlogin):
        try:
            valor = obtenedor()
            if valor:
                return str(valor).strip().lower()
        except Exception:
            pass

    for clave in ("USER", "USERNAME"):
        valor = os.environ.get(clave)
        if valor:
            return str(valor).strip().lower()

    return "desconocido"
