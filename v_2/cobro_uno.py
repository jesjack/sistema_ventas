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


def _crear_dialogo(uno_context, total, error_texto=""):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 80
    dialog_model.Width = 210
    dialog_model.Height = 104
    dialog_model.Title = "Cobro de venta"

    instruccion_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    instruccion_model.Name = "lblInstruccion"
    instruccion_model.PositionX = 8
    instruccion_model.PositionY = 8
    instruccion_model.Width = 194
    instruccion_model.Height = 12
    instruccion_model.Label = "Ingrese el monto entregado por el cliente."
    dialog_model.insertByName("lblInstruccion", instruccion_model)

    label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    label_model.Name = "lblTotal"
    label_model.PositionX = 8
    label_model.PositionY = 22
    label_model.Width = 194
    label_model.Height = 12
    label_model.Label = f"Total: ${float(total):.2f}"
    dialog_model.insertByName("lblTotal", label_model)

    monto_label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    monto_label_model.Name = "lblMonto"
    monto_label_model.PositionX = 8
    monto_label_model.PositionY = 38
    monto_label_model.Width = 76
    monto_label_model.Height = 12
    monto_label_model.Label = "Monto recibido:"
    dialog_model.insertByName("lblMonto", monto_label_model)

    edit_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    edit_model.Name = "txtMonto"
    edit_model.PositionX = 88
    edit_model.PositionY = 36
    edit_model.Width = 114
    edit_model.Height = 14
    edit_model.Text = ""
    dialog_model.insertByName("txtMonto", edit_model)

    error_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    error_model.Name = "lblError"
    error_model.PositionX = 8
    error_model.PositionY = 56
    error_model.Width = 194
    error_model.Height = 20
    error_model.MultiLine = True
    error_model.Label = error_texto
    dialog_model.insertByName("lblError", error_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 96
    ok_model.PositionY = 80
    ok_model.Width = 46
    ok_model.Height = 14
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    cancel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_model.Name = "btnCancel"
    cancel_model.PositionX = 146
    cancel_model.PositionY = 80
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
            recibido = _parse_monto(texto)
        except ValueError:
            error_texto = "El monto ingresado no es valido. Usa solo numeros y, si hace falta, coma o punto decimal."
            continue

        if recibido < total:
            error_texto = f"El monto recibido es menor al total. Faltan ${total - recibido:.2f}."
            continue

        cambio = recibido - total
        return float(recibido), float(cambio)