from dialogs._base import ConstructorDialogo, mostrar_y_cerrar


def _crear_dialogo_aviso(uno_context, mensaje):
    c = ConstructorDialogo(uno_context, "Impresión en curso", 250, 92)
    c.etiqueta("lblMensaje", 8, 12, 234, 24, mensaje, multilinea=True)
    c.boton("btnOk", 96, 58, 58, 14, "Aceptar", 1, por_defecto=True)
    return c.crear()


def mostrar_aviso_impresion(uno_context, mensaje="Imprimiendo, espere por favor."):
    mostrar_y_cerrar(_crear_dialogo_aviso(uno_context, mensaje))
