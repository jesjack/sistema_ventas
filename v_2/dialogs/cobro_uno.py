from dialogs._base import ConstructorDialogo
from dialogs.parseo import parse_monto


def _crear_dialogo(uno_context, total, error_texto=""):
    c = ConstructorDialogo(uno_context, "Cobro de venta", 210, 104)
    c.etiqueta("lblInstruccion", 8, 8, 194, 12, "Ingrese el monto entregado por el cliente.")
    c.etiqueta("lblTotal", 8, 22, 194, 12, f"Total: ${float(total):.2f}")
    c.etiqueta("lblMonto", 8, 38, 76, 12, "Monto recibido:")
    c.campo("txtMonto", 88, 36, 114, 14)
    c.etiqueta("lblError", 8, 56, 194, 20, error_texto, multilinea=True)
    c.aceptar_cancelar(80)
    return c.crear()


def solicitar_monto_cliente(total, uno_context):
    total = float(total)
    error_texto = ""

    while True:
        dialog = _crear_dialogo(uno_context, total, error_texto)
        try:
            result = dialog.execute()
            if result != 1:
                return None

            texto = dialog.getControl("txtMonto").getModel().Text
        finally:
            dialog.dispose()

        try:
            recibido = parse_monto(texto)
        except ValueError:
            error_texto = "El monto ingresado no es válido. Usa solo números y, si hace falta, coma o punto decimal."
            continue

        if recibido < total:
            error_texto = f"El monto recibido es menor al total. Faltan ${total - recibido:.2f}."
            continue

        cambio = recibido - total
        return float(recibido), float(cambio)