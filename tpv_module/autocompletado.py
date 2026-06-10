from __future__ import annotations

import time
from typing import List

PREPOSICIONES = {
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "y",
    "o",
}

LOG_PATH = "/tmp/tpv_tab_debug.log"


def log_debug(msg: str) -> None:
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def es_preposicion(palabra: str) -> bool:
    return palabra.strip().lower() in PREPOSICIONES


def generar_acronimo(nombre: str) -> str:
    resultado: List[str] = []
    for palabra in nombre.split(" "):
        p = palabra.strip()
        if p and not es_preposicion(p):
            resultado.append(p[0].lower())
    return "".join(resultado)


def prefijo_comun_palabras(a: str, b: str) -> str:
    p_a = a.split(" ")
    p_b = b.split(" ")
    limite = min(len(p_a), len(p_b))

    comunes: List[str] = []
    for i in range(limite):
        if p_a[i].lower() == p_b[i].lower():
            comunes.append(p_a[i])
        else:
            break
    return " ".join(comunes)


def obtener_catalogo(hoja) -> List[str]:
    lista: List[str] = []
    fila = 2  # L3 en base 0

    while True:
        valor = hoja.getCellByPosition(11, fila).String.strip()
        if not valor:
            break
        lista.append(valor)
        fila += 1

    return lista


def expandir_acronimos(input_texto: str, catalogo: List[str]) -> str:
    claves: dict[str, str] = {}

    for producto in catalogo:
        acr = generar_acronimo(producto)
        if acr in claves:
            claves[acr] = prefijo_comun_palabras(claves[acr], producto)
        else:
            claves[acr] = producto

    resultado: List[str] = []
    tokens = input_texto.strip().lower().split(" ")

    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue

        expandido = tok
        coincidencias: List[str] = []
        for acr, valor in claves.items():
            if acr.startswith(tok):
                coincidencias.append(valor)

        if coincidencias:
            expandido = coincidencias[0]
            for candidato in coincidencias[1:]:
                expandido = prefijo_comun_palabras(expandido, candidato)

        resultado.append(expandido)

    return " ".join(resultado)


def producto_matchea(nombre: str, tokens: List[str]) -> bool:
    nombre_lower = nombre.lower()
    for tok in tokens:
        t = tok.strip().lower()
        if t and t not in nombre_lower:
            return False
    return True


def autocompletar_b3(hoja, doc=None, password: str = "") -> bool:
    celda_b3 = hoja.getCellRangeByName("B3")
    input_raw = celda_b3.String
    log_debug(f"autocompletar_b3 inicio input_raw={input_raw!r}")

    estaba_protegida = False
    try:
        estaba_protegida = bool(hoja.isProtected())
    except Exception:
        estaba_protegida = False

    try:
        if estaba_protegida:
            hoja.unprotect(password)
        # time.sleep(1)
        # celda_b3.String = "autocompletado"
        log_debug("autocompletar_b3 escribio 'autocompletado'")
    finally:
        if estaba_protegida:
            hoja.protect(password)

    if doc is None:
        return True

    try:
        from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
        from com.sun.star.awt.MessageBoxType import INFOBOX

        ctx = doc.getParent()
        toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        frame = doc.getCurrentController().getFrame()
        ventana_padre = frame.getContainerWindow()
        mensaje = f"Antes en B3: {input_raw}"
        modal = toolkit.createMessageBox(ventana_padre, INFOBOX, BUTTONS_OK, "Prueba TAB", mensaje)
        modal.execute()
        modal.dispose()
        log_debug("autocompletar_b3 modal mostrado")
    except Exception:
        log_debug("autocompletar_b3 no pudo mostrar modal")
        pass

    return True
