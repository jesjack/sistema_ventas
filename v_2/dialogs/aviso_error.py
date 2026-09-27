from dialogs._base import ConstructorDialogo, mostrar_y_cerrar


def _crear_dialogo_error(uno_context, titulo, mensaje):
    c = ConstructorDialogo(uno_context, titulo, 250, 128)
    c.etiqueta("lblMensaje", 8, 12, 234, 84, mensaje, multilinea=True)
    c.boton("btnOk", 96, 104, 58, 14, "Aceptar", 1, por_defecto=True)
    return c.crear()


def mostrar_aviso_error(uno_context, mensaje, titulo="Aviso del sistema"):
    mostrar_y_cerrar(_crear_dialogo_error(uno_context, titulo, mensaje))
