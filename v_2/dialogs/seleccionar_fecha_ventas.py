from datetime import datetime


def _normalizar_fecha(texto):
    valor = str(texto).strip()
    if not valor:
        raise ValueError("fecha vacia")

    return datetime.strptime(valor, "%d-%m-%Y").strftime("%Y-%m-%d")


def formatear_fecha_ventas(fecha_iso):
    return datetime.strptime(str(fecha_iso), "%Y-%m-%d").strftime("%d-%m-%Y")


def _crear_dialogo(uno_context, error_texto=""):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 80
    dialog_model.Width = 230
    dialog_model.Height = 108
    dialog_model.Title = "Seleccionar fecha"

    instruccion_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    instruccion_model.Name = "lblInstruccion"
    instruccion_model.PositionX = 8
    instruccion_model.PositionY = 8
    instruccion_model.Width = 214
    instruccion_model.Height = 12
    instruccion_model.Label = "Ingrese la fecha en formato DD-MM-YYYY."
    dialog_model.insertByName("lblInstruccion", instruccion_model)

    fecha_label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    fecha_label_model.Name = "lblFecha"
    fecha_label_model.PositionX = 8
    fecha_label_model.PositionY = 28
    fecha_label_model.Width = 76
    fecha_label_model.Height = 12
    fecha_label_model.Label = "Fecha (dd-mm-aaaa):"
    dialog_model.insertByName("lblFecha", fecha_label_model)

    edit_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    edit_model.Name = "txtFecha"
    edit_model.PositionX = 88
    edit_model.PositionY = 26
    edit_model.Width = 130
    edit_model.Height = 14
    edit_model.Text = datetime.now().strftime("%d-%m-%Y")
    edit_model.MaxTextLen = 10
    dialog_model.insertByName("txtFecha", edit_model)

    error_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    error_model.Name = "lblError"
    error_model.PositionX = 8
    error_model.PositionY = 48
    error_model.Width = 214
    error_model.Height = 18
    error_model.MultiLine = True
    error_model.Label = error_texto
    dialog_model.insertByName("lblError", error_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 128
    ok_model.PositionY = 74
    ok_model.Width = 46
    ok_model.Height = 14
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    cancel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_model.Name = "btnCancel"
    cancel_model.PositionX = 178
    cancel_model.PositionY = 74
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
            error_texto = "La fecha no es valida. Use el formato dd-mm-aaaa."