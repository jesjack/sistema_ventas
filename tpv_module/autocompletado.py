from __future__ import annotations

import tkinter as tk
import time
from typing import List, Optional

from tpv_module.completion_byjesjack import buscar, productos, quitar_preposiciones

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
RESULT_PATH = "/tmp/tpv_autocompletado_resultado.txt"


def log_debug(msg: str) -> None:
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def escribir_resultado(valor: str) -> None:
    try:
        with open(RESULT_PATH, "w") as f:
            f.write(valor)
        log_debug(f"Resultado escrito en {RESULT_PATH}: {valor!r}")
    except Exception as e:
        log_debug(f"Error escribiendo resultado: {e}")


TABLA_PRODUCTOS = quitar_preposiciones(productos)


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


def buscar_opciones(siglas: str) -> List[str]:
    siglas = (siglas or "").strip().lower().replace(" ", "")
    if not siglas:
        return []

    coincidencias = buscar(TABLA_PRODUCTOS, siglas)
    return [fila[0] for fila in coincidencias]


def seleccionar_opcion_tk(opciones: List[str], texto_base: str) -> Optional[str]:
    if not opciones:
        return None

    resultado: dict[str, Optional[str]] = {"value": None}

    root = tk.Tk()
    root.title("Opciones de autocompletado")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    ancho = 520
    alto = min(320, 90 + (len(opciones) * 24))
    x = max(40, (root.winfo_screenwidth() // 2) - (ancho // 2))
    y = max(40, (root.winfo_screenheight() // 2) - (alto // 2))
    root.geometry(f"{ancho}x{alto}+{x}+{y}")

    marco = tk.Frame(root, padx=12, pady=12)
    marco.pack(fill="both", expand=True)

    titulo = tk.Label(
        marco,
        text=f"{texto_base}  |  usa flechas y Enter/Tab",
        anchor="w",
        justify="left",
    )
    titulo.pack(fill="x", pady=(0, 8))

    contenedor_lista = tk.Frame(marco)
    contenedor_lista.pack(fill="both", expand=True)

    barra = tk.Scrollbar(contenedor_lista, orient="vertical")
    barra.pack(side="right", fill="y")

    lista = tk.Listbox(
        contenedor_lista,
        height=min(10, len(opciones)),
        activestyle="dotbox",
        yscrollcommand=barra.set,
    )
    lista.pack(side="left", fill="both", expand=True)
    barra.configure(command=lista.yview)

    for opcion in opciones:
        lista.insert(tk.END, opcion)

    lista.selection_set(0)
    lista.activate(0)
    root.update_idletasks()
    root.lift()
    root.focus_force()
    root.grab_set()

    def enfocar_lista() -> None:
        try:
            lista.selection_clear(0, tk.END)
            lista.selection_set(0)
            lista.activate(0)
            lista.see(0)
            lista.focus_set()
        except Exception:
            pass

    root.after(0, enfocar_lista)

    def elegir_actual(_event=None):
        seleccion = lista.curselection()
        if not seleccion:
            seleccion = (0,)
        resultado["value"] = lista.get(seleccion[0])
        try:
            root.grab_release()
        except Exception:
            pass
        root.destroy()
        return "break"

    def cerrar(_event=None):
        try:
            root.grab_release()
        except Exception:
            pass
        root.destroy()
        return "break"

    def mover_abajo(_event=None):
        actual = list(lista.curselection() or (0,))
        indice = min(actual[0] + 1, lista.size() - 1)
        lista.selection_clear(0, tk.END)
        lista.selection_set(indice)
        lista.activate(indice)
        lista.see(indice)
        return "break"

    def mover_arriba(_event=None):
        actual = list(lista.curselection() or (0,))
        indice = max(actual[0] - 1, 0)
        lista.selection_clear(0, tk.END)
        lista.selection_set(indice)
        lista.activate(indice)
        lista.see(indice)
        return "break"

    lista.bind("<KeyRelease-Return>", elegir_actual)
    lista.bind("<KeyRelease-Tab>", elegir_actual)
    lista.bind("<Escape>", cerrar)
    lista.bind("<Down>", mover_abajo)
    lista.bind("<Up>", mover_arriba)
    lista.bind("<Double-Button-1>", elegir_actual)
    root.bind("<KeyRelease-Return>", elegir_actual)
    root.bind("<KeyRelease-Tab>", elegir_actual)
    root.bind("<Escape>", cerrar)
    root.bind("<Down>", mover_abajo)
    root.bind("<Up>", mover_arriba)
    root.protocol("WM_DELETE_WINDOW", cerrar)

    log_debug(f"Ventana Tk abierta con {len(opciones)} opciones")
    try:
        root.mainloop()
    finally:
        try:
            root.grab_release()
        except Exception:
            pass
    return resultado["value"]


def autocompletar_b3(hoja, doc=None, password: str = "") -> bool:
    celda_b3 = hoja.getCellRangeByName("B3")
    input_raw = celda_b3.String
    log_debug(f"autocompletar_b3 inicio input_raw={input_raw!r}")

    opciones = buscar_opciones(input_raw)
    log_debug(f"autocompletar_b3 opciones={opciones!r}")

    if not opciones:
        log_debug("autocompletar_b3 sin opciones")
        return False

    if len(opciones) == 1:
        opcion_elegida = opciones[0]
    else:
        opcion_elegida = seleccionar_opcion_tk(opciones, input_raw)

    if not opcion_elegida:
        log_debug("autocompletar_b3 cancelado por usuario")
        return False

    log_debug(f"autocompletar_b3 escribiendo resultado: {opcion_elegida!r}")
    escribir_resultado(opcion_elegida)

    return True
