from dialogs._base import ConstructorDialogo


def _crear_dialogo_codigo(uno_context, error_texto=""):
    c = ConstructorDialogo(uno_context, "Ingreso de código", 210, 94)
    c.etiqueta("lblInstruccion", 8, 8, 194, 12, "Ingrese el código solicitado.")
    c.etiqueta("lblCodigo", 8, 28, 76, 12, "Código:")
    c.campo("txtCodigo", 88, 26, 114, 14)
    c.etiqueta("lblError", 8, 46, 194, 16, error_texto, multilinea=True)
    c.aceptar_cancelar(68)
    return c.crear()


def solicitar_codigo(uno_context):
    error_texto = ""

    while True:
        dialog = _crear_dialogo_codigo(uno_context, error_texto)
        try:
            result = dialog.execute()
            if result != 1:
                return None

            codigo = dialog.getControl("txtCodigo").getModel().Text.strip()
        finally:
            dialog.dispose()

        if not codigo:
            error_texto = "El código no puede estar vacío."
            continue

        return codigo