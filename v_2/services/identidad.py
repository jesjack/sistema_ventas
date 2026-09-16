from __future__ import annotations

import getpass
import os

# Usuario ficticio en usuarios_sistema (nunca se loguea de verdad con este
# nombre) cuyos permisos de boton_visibilidad sirven de plantilla: al primer
# login de un usuario real nuevo, se le copian los botones que tenga
# otorgados este usuario -- ver BotonesService.otorgar_plantilla_a_usuario_nuevo.
USUARIO_PLANTILLA = "__default__"


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
