from __future__ import annotations

from dialogs._base import ConstructorDialogo
from dialogs.parseo import parse_monto


def _crear_dialogo(uno_context, producto, codigo_barras, error_texto=""):
    c = ConstructorDialogo(uno_context, "Registrar código de barras", 230, 124)
    c.etiqueta("lblInstruccion", 8, 8, 214, 12, "Ingrese el precio de venta para el producto seleccionado.")
    c.etiqueta("lblProducto", 8, 24, 214, 12, f"Producto: {producto}")
    c.etiqueta("lblCodigo", 8, 40, 214, 12, f"Código: {codigo_barras}")
    c.etiqueta("lblPrecio", 8, 56, 76, 12, "Precio venta:")
    c.campo("txtPrecio", 88, 54, 134, 14)
    c.etiqueta("lblError", 8, 74, 214, 18, error_texto, multilinea=True)
    c.aceptar_cancelar(98, x_aceptar=128, x_cancelar=178)
    return c.crear()


def solicitar_precio_venta(uno_context, producto, codigo_barras):
    error_texto = ""

    while True:
        dialog = _crear_dialogo(uno_context, producto, codigo_barras, error_texto)
        try:
            result = dialog.execute()
            if result != 1:
                return None

            texto = dialog.getControl("txtPrecio").getModel().Text
        finally:
            dialog.dispose()

        try:
            precio = parse_monto(texto)
        except ValueError:
            error_texto = "El precio ingresado no es válido. Usa solo números y, si hace falta, coma o punto decimal."
            continue

        if precio is None or precio < 0:
            error_texto = "El precio de venta debe ser mayor o igual a cero."
            continue

        return float(precio)
