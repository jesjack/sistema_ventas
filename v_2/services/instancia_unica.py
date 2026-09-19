"""Garantiza que solo UN usuario del equipo tenga abierto el sistema: el ultimo
que lo abrio se queda con el, y se cierra el de los demas.

El puerto UNO (2002) es unico por maquina: si otro usuario ya tiene su
LibreOffice escuchando ahi, el de este usuario no puede abrirlo y main.py (que
corre como root) terminaria conectado al documento del OTRO usuario, sin que
nada responda del lado del usuario actual.

main.py llama a asegurar_instancia_unica() al arrancar. Si el dueno del puerto
es otro usuario, aqui se le cierra todo (launcher, main.py, LibreOffice) y se
pide al launcher de ESTE usuario (open_system.sh, via relanzar.flag) que
arranque de nuevo con el puerto libre. Solo usa /proc (sin psutil, que no esta
instalado en el Python global).

Si el puerto no se libera en ESPERA_PUERTO segundos se muestra una advertencia
en pantalla (zenity, como el usuario) y main.py sale sin relanzar.
"""
from __future__ import annotations

import os
import pwd
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from services.modo_sistema import solicitar_relanzamiento as _solicitar_relanzamiento

BASE_DIR = Path(__file__).resolve().parent.parent
PUERTO_UNO = 2002

GRACIA_TERM = 5.0  # segundos entre SIGTERM y SIGKILL
ESPERA_PUERTO = 60.0  # segundos maximos para que el puerto quede libre (o sea de este usuario)
ESPERA_MAIN = 5.0  # segundos para que un main.py ajeno salga solo (corre sus atexit)


def uid_propio() -> int:
    # main.py corre con sudo: getuid() daria 0. SUDO_UID es el usuario real.
    try:
        return int(os.environ["SUDO_UID"])
    except (KeyError, ValueError):
        return os.getuid()


# ---------------------------------------------------------------- /proc ----

def _pids() -> list[int]:
    return [int(nombre) for nombre in os.listdir("/proc") if nombre.isdigit()]


def _leer_stat(pid: int):
    """(comm, estado, ppid) o None si el proceso ya no existe."""
    try:
        datos = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm va entre parentesis y puede traer espacios: se corta por el ultimo ")".
    izquierda, _, derecha = datos.rpartition(")")
    campos = derecha.split()
    try:
        return izquierda.partition("(")[2], campos[0], int(campos[1])
    except (IndexError, ValueError):
        return None


def _cmdline(pid: int) -> list[str]:
    try:
        crudo = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [arg.decode(errors="replace") for arg in crudo.split(b"\0") if arg]


def _uid_de(pid: int):
    try:
        return os.stat(f"/proc/{pid}").st_uid
    except OSError:
        return None


def _cwd(pid: int):
    try:
        return os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        return None


def _vivo(pid: int) -> bool:
    stat = _leer_stat(pid)
    return stat is not None and stat[1] != "Z"  # un zombie ya esta muerto


def _ancestros(pid: int) -> set[int]:
    """pid y toda su cadena de padres (incluye al sudo que nos lanzo)."""
    cadena = set()
    while pid > 1 and pid not in cadena:
        cadena.add(pid)
        stat = _leer_stat(pid)
        if stat is None:
            break
        pid = stat[2]
    return cadena


def pid_escuchando(puerto: int):
    """PID que escucha en el puerto TCP, o None (nadie, o no se pudo ver: leer
    los fd de procesos ajenos requiere root)."""
    inodos = set()
    for tabla in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lineas = Path(tabla).read_text().splitlines()[1:]
        except OSError:
            continue
        for linea in lineas:
            columnas = linea.split()
            if len(columnas) < 10 or columnas[3] != "0A":  # 0A = LISTEN
                continue
            if int(columnas[1].rpartition(":")[2], 16) == puerto:
                inodos.add(columnas[9])

    if not inodos:
        return None

    objetivos = {f"socket:[{inodo}]" for inodo in inodos}
    for pid in _pids():
        try:
            descriptores = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in descriptores:
            try:
                destino = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if destino in objetivos:
                return pid
    return None


# ------------------------------------------------------------- busqueda ----

def _es_launcher(pid: int, base: str) -> bool:
    return (any(Path(arg).name == "open_system.sh" for arg in _cmdline(pid))
            and _cwd(pid) == base)


def _lanzadores_a_cerrar(base_dir: Path, uid: int, ancestros: set[int]) -> list[int]:
    """Todos los open_system.sh de este proyecto salvo el MIO (su bucle
    relanzaria el sistema al morir su LibreOffice, o competiria por la
    bandera relanzar.flag y por el puerto).

    Mi launcher es el que esta entre mis ancestros (main.py <- sudo <-
    soffice.bin <- oosplash <- open_system.sh). Si esa cadena esta rota y no
    lo encuentro, solo se cierran los de OTROS usuarios: mejor dejar vivo un
    launcher viejo que matar el que tiene que relanzar este sistema."""
    base = os.path.realpath(base_dir)
    todos = [pid for pid in _pids() if pid not in ancestros and _es_launcher(pid, base)]
    tengo_launcher = any(_es_launcher(pid, base) for pid in ancestros)
    if tengo_launcher:
        return todos
    return [pid for pid in todos if _uid_de(pid) not in (None, uid)]


def _mains_ajenos(base_dir: Path) -> list[int]:
    """Todos los main.py de este proyecto (y su sudo) salvo este proceso y sus
    ancestros. Son root, asi que el uid no distingue de quien son: como solo
    puede haber un sistema activo, cualquier otro es viejo o ajeno."""
    ruta = str(base_dir / "main.py")
    propios = _ancestros(os.getpid())
    encontrados = []
    for pid in _pids():
        if pid in propios:
            continue
        stat = _leer_stat(pid)
        if stat is None or not (stat[0].startswith("python") or stat[0] == "sudo"):
            continue
        if ruta in _cmdline(pid):
            encontrados.append(pid)
    return encontrados


def _libreoffice_del_puerto(dueno: int) -> list[int]:
    """El proceso que escucha y su oosplash padre (si lo tiene)."""
    pids = [dueno]
    stat = _leer_stat(dueno)
    if stat is not None:
        padre = _leer_stat(stat[2])
        if padre is not None and padre[0] == "oosplash":
            pids.append(stat[2])
    return pids


def _libreoffice_propio(uid: int, puerto: int) -> list[int]:
    """LibreOffice de este usuario lanzado por open_system.sh (lleva el
    --accept del puerto). No se tocan otros documentos que tenga abiertos."""
    marca = f"port={puerto}"
    encontrados = []
    for pid in _pids():
        if _uid_de(pid) != uid:
            continue
        stat = _leer_stat(pid)
        if stat is None or stat[0] not in ("soffice.bin", "oosplash"):
            continue
        if any(marca in arg for arg in _cmdline(pid)):
            encontrados.append(pid)
    return encontrados


# ------------------------------------------------------------- acciones ----

def _senal(pid: int, senal: int) -> None:
    try:
        os.kill(pid, senal)
    except OSError:
        pass


def _esperar_salida(pids: list[int], segundos: float) -> None:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite and any(_vivo(pid) for pid in pids):
        time.sleep(0.1)


def _terminar(pids: list[int], gracia: float = GRACIA_TERM) -> None:
    """SIGTERM y, si tras `gracia` segundos sigue vivo, SIGKILL."""
    pids = [pid for pid in pids if _vivo(pid)]
    for pid in pids:
        _senal(pid, signal.SIGTERM)
    _esperar_salida(pids, gracia)
    for pid in pids:
        if _vivo(pid):
            print(f"[instancia] El proceso {pid} no salió con SIGTERM; enviando SIGKILL.")
            _senal(pid, signal.SIGKILL)
    _esperar_salida(pids, 2.0)


def _esperar_puerto_libre(puerto: int, segundos: float) -> bool:
    limite = time.monotonic() + segundos
    while pid_escuchando(puerto) is not None:
        if time.monotonic() >= limite:
            return False
        time.sleep(0.2)
    return True


def _entorno_grafico(uid: int, ancestros: set[int]) -> dict:
    """Entorno de pantalla del usuario, tomado de alguno de mis ancestros (su
    LibreOffice): sudo borra DISPLAY y demas, y main.py corre como root."""
    claves = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
    for pid in sorted(ancestros, reverse=True):
        try:
            crudo = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            continue
        entorno = {}
        for par in crudo.split(b"\0"):
            clave, _, valor = par.decode(errors="replace").partition("=")
            if clave in claves and valor:
                entorno[clave] = valor
        if "DISPLAY" in entorno or "WAYLAND_DISPLAY" in entorno:
            entorno.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
            return entorno
    return {}


def _avisar_en_pantalla(titulo: str, mensaje: str, uid: int, ancestros: set[int]) -> None:
    """Advertencia visible (zenity, como el usuario, sin bloquear a main.py).
    Cualquier fallo se ignora: el mensaje ya quedo tambien en el log."""
    try:
        entorno = _entorno_grafico(uid, ancestros)
        zenity = shutil.which("zenity")
        if not entorno or not zenity:
            return
        opciones = {}
        if os.getuid() == 0 and uid != 0:
            datos = pwd.getpwuid(uid)
            opciones = {"user": uid, "group": datos.pw_gid, "extra_groups": []}
            entorno["HOME"] = datos.pw_dir
        subprocess.Popen(
            [zenity, "--warning", "--width=520", "--no-markup", f"--title={titulo}", f"--text={mensaje}"],
            env=entorno, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **opciones,
        )
    except Exception as exc:
        print(f"[instancia] No se pudo mostrar la advertencia en pantalla: {exc}")


def _describir(pid: int) -> str:
    return f"pid {pid}, uid {_uid_de(pid)}, {' '.join(_cmdline(pid))[:120] or '?'}"


def asegurar_instancia_unica(
    puerto: int = PUERTO_UNO,
    base_dir: Path = BASE_DIR,
    uid: int | None = None,
    solicitar_relanzamiento=_solicitar_relanzamiento,
    avisar=_avisar_en_pantalla,
) -> bool:
    """True: este proceso puede seguir con normalidad (el puerto es de este
    usuario, o nadie lo tiene). False: main.py debe terminar ya, sea porque se
    pidio el relanzamiento o porque no se pudo desplazar al otro usuario."""
    if not sys.platform.startswith("linux"):
        return True  # en Windows hay un solo usuario

    uid = uid_propio() if uid is None else uid

    dueno = pid_escuchando(puerto)
    if dueno is None:
        return True

    uid_dueno = _uid_de(dueno)
    if uid_dueno is None or uid_dueno == uid:
        return True

    print(f"[instancia] El puerto {puerto} lo tiene el usuario uid={uid_dueno} (pid {dueno}); "
          f"se cierra su sistema para que este usuario lo tome.")

    ancestros = _ancestros(os.getpid())

    # Orden importa: primero los launchers, para que al morir su LibreOffice
    # no relancen el sistema al ver la bandera relanzar.flag (compartida).
    _terminar(_lanzadores_a_cerrar(base_dir, uid, ancestros))

    mains = _mains_ajenos(base_dir)
    _terminar(_libreoffice_del_puerto(dueno))
    # Sus main.py salen solos al perder el documento y asi corren sus atexit
    # (cierre de sesion de usuario); solo se fuerza a los que no lo logren.
    _esperar_salida(mains, ESPERA_MAIN)
    _terminar(mains, gracia=2.0)

    # Se espera a que el puerto quede libre. Si reaparece un dueno ajeno
    # (otro launcher, otro LibreOffice) se le cierra de nuevo; si lo toma un
    # proceso de ESTE usuario ya no hay nada que hacer: el sistema es nuestro.
    limite = time.monotonic() + ESPERA_PUERTO
    while True:
        actual = pid_escuchando(puerto)
        if actual is None:
            break
        uid_actual = _uid_de(actual)
        if uid_actual == uid:
            print(f"[instancia] El puerto {puerto} lo tomó un proceso de este usuario ({_describir(actual)}); se continúa sin relanzar.")
            return True
        if time.monotonic() >= limite:
            detalle = _describir(actual)
            print(f"[instancia] ERROR: tras {ESPERA_PUERTO:.0f} s el puerto {puerto} sigue ocupado por {detalle}; no se relanza para no entrar en bucle.")
            avisar(
                "No se pudo abrir el sistema de ventas",
                f"El puerto {puerto} de LibreOffice sigue ocupado por otro proceso y no se pudo cerrar "
                f"tras {ESPERA_PUERTO:.0f} segundos:\n\n{detalle}\n\n"
                "El sistema NO se abrió. Cierre ese proceso (o reinicie el equipo) e inténtelo de nuevo.",
                uid, ancestros,
            )
            return False
        if uid_actual is not None:
            _terminar(_lanzadores_a_cerrar(base_dir, uid, ancestros), gracia=1.0)
            _terminar(_libreoffice_del_puerto(actual), gracia=1.0)
        time.sleep(0.5)

    print("[instancia] Puerto libre; se reinicia el sistema de este usuario.")
    solicitar_relanzamiento()
    _terminar(_libreoffice_propio(uid, puerto))
    return False
