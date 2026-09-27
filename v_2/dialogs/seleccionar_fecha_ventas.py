from datetime import datetime

from dialogs._base import ConstructorDialogo


def _normalizar_fecha(texto):
    valor = str(texto).strip()
    if not valor:
        raise ValueError("fecha vacia")

    return datetime.strptime(valor, "%d-%m-%Y").strftime("%Y-%m-%d")


def formatear_fecha_ventas(fecha_iso):
    return datetime.strptime(str(fecha_iso), "%Y-%m-%d").strftime("%d-%m-%Y")


def _crear_dialogo(uno_context, error_texto=""):
    c = ConstructorDialogo(uno_context, "Seleccionar fecha", 230, 108)
    c.etiqueta("lblInstruccion", 8, 8, 214, 12, "Ingrese la fecha en formato DD-MM-AAAA.")
    c.etiqueta("lblFecha", 8, 28, 76, 12, "Fecha (dd-mm-aaaa):")
    c.campo("txtFecha", 88, 26, 130, 14, texto=datetime.now().strftime("%d-%m-%Y"), max_len=10)
    c.etiqueta("lblError", 8, 48, 214, 18, error_texto, multilinea=True)
    c.aceptar_cancelar(74, x_aceptar=128, x_cancelar=178)
    return c.crear()


def solicitar_fecha_ventas(uno_context):
    error_texto = ""

    while True:
        dialog = _crear_dialogo(uno_context, error_texto)
        try:
            result = dialog.execute()
            if result != 1:
                return None

            texto = dialog.getControl("txtFecha").getModel().Text
        finally:
            dialog.dispose()

        try:
            return _normalizar_fecha(texto)
        except ValueError:
            error_texto = "La fecha no es válida. Use el formato dd-mm-aaaa."