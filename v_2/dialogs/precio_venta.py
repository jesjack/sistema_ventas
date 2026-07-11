from __future__ import annotations


def _parse_monto(texto):
    if texto is None:
        return None

    limpio = str(texto).strip().replace(" ", "")
    if not limpio:
        raise ValueError("monto vacio")

    if "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")

    return float(limpio)


def _crear_dialogo(uno_context, producto, codigo_barras, error_texto=""):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 80
    dialog_model.Width = 230
    dialog_model.Height = 124
    dialog_model.Title = "Registrar codigo de barras"

    instruccion_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    instruccion_model.Name = "lblInstruccion"
    instruccion_model.PositionX = 8
    instruccion_model.PositionY = 8
    instruccion_model.Width = 214
    instruccion_model.Height = 12
    instruccion_model.Label = "Ingrese el precio de venta para el producto seleccionado."
    dialog_model.insertByName("lblInstruccion", instruccion_model)

    producto_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    producto_model.Name = "lblProducto"
    producto_model.PositionX = 8
    producto_model.PositionY = 24
    producto_model.Width = 214
    producto_model.Height = 12
    producto_model.Label = f"Producto: {producto}"
    dialog_model.insertByName("lblProducto", producto_model)

    codigo_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    codigo_model.Name = "lblCodigo"
    codigo_model.PositionX = 8
    codigo_model.PositionY = 40
    codigo_model.Width = 214
    codigo_model.Height = 12
    codigo_model.Label = f"Codigo: {codigo_barras}"
    dialog_model.insertByName("lblCodigo", codigo_model)

    precio_label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    precio_label_model.Name = "lblPrecio"
    precio_label_model.PositionX = 8
    precio_label_model.PositionY = 56
    precio_label_model.Width = 76
    precio_label_model.Height = 12
    precio_label_model.Label = "Precio venta:"
    dialog_model.insertByName("lblPrecio", precio_label_model)

    edit_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    edit_model.Name = "txtPrecio"
    edit_model.PositionX = 88
    edit_model.PositionY = 54
    edit_model.Width = 134
    edit_model.Height = 14
    edit_model.Text = ""
    dialog_model.insertByName("txtPrecio", edit_model)

    error_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    error_model.Name = "lblError"
    error_model.PositionX = 8
    error_model.PositionY = 74
    error_model.Width = 214
    error_model.Height = 18
    error_model.MultiLine = True
    error_model.Label = error_texto
    dialog_model.insertByName("lblError", error_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 128
    ok_model.PositionY = 98
    ok_model.Width = 46
    ok_model.Height = 14
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    cancel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_model.Name = "btnCancel"
    cancel_model.PositionX = 178
    cancel_model.PositionY = 98
    cancel_model.Width = 46
    cancel_model.Height = 14
    cancel_model.Label = "Cancelar"
    cancel_model.PushButtonType = 2
    dialog_model.insertByName("btnCancel", cancel_model)

    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", uno_context)
    dialog.setModel(dialog_model)
    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)
    dialog.createPeer(toolkit, None)
    return dialog


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
            precio = _parse_monto(texto)
        except ValueError:
            error_texto = "El precio ingresado no es valido. Usa solo numeros y, si hace falta, coma o punto decimal."
            continue

        if precio is None or precio < 0:
            error_texto = "El precio de venta debe ser mayor o igual a cero."
            continue

        return float(precio)
