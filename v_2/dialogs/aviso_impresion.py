from dialogs._base import ConstructorDialogo, EscuchaAccion, mostrar_y_cerrar


def _crear_dialogo_aviso(uno_context, mensaje, con_reintentar=False):
    c = ConstructorDialogo(uno_context, "Impresión en curso", 250, 92)
    c.etiqueta("lblMensaje", 8, 12, 234, 36, mensaje, multilinea=True)
    if con_reintentar:
        c.boton("btnReintentar", 60, 58, 64, 14, "Reintentar")
        c.boton("btnOk", 128, 58, 58, 14, "Aceptar", 1, por_defecto=True)
    else:
        c.boton("btnOk", 96, 58, 58, 14, "Aceptar", 1, por_defecto=True)
    return c.crear()


def mostrar_aviso_impresion(uno_context, mensaje="Imprimiendo, espere por favor.", reintentar=None):
    """Con `reintentar` (una función que vuelve a mandar lo mismo a la impresora), aparece el botón
    "Reintentar" por si la impresora falló; el aviso sigue abierto para poder reintentar otra vez."""
    dialog = _crear_dialogo_aviso(uno_context, mensaje, con_reintentar=reintentar is not None)
    if reintentar is None:
        mostrar_y_cerrar(dialog)
        return

    etiqueta = dialog.getControl("lblMensaje").getModel()
    intentos = {"n": 1}

    def volver_a_imprimir():
        try:
            reintentar()
        except Exception as exc:
            print(f"No se pudo reintentar la impresión: {exc}")
            etiqueta.Label = f"No se pudo reintentar la impresión: {exc}"
            return
        intentos["n"] += 1
        etiqueta.Label = f"Se volvió a mandar a la impresora (intento {intentos['n']}). Imprimiendo, espere por favor."

    escucha = EscuchaAccion(volver_a_imprimir)  # se conserva mientras el aviso esté abierto
    dialog.getControl("btnReintentar").addActionListener(escucha)
    mostrar_y_cerrar(dialog)
    del escucha
