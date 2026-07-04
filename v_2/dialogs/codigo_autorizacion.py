def _crear_dialogo_codigo(uno_context, error_texto=""):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 80
    dialog_model.Width = 210
    dialog_model.Height = 94
    dialog_model.Title = "Ingreso de codigo"

    instruccion_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    instruccion_model.Name = "lblInstruccion"
    instruccion_model.PositionX = 8
    instruccion_model.PositionY = 8
    instruccion_model.Width = 194
    instruccion_model.Height = 12
    instruccion_model.Label = "Ingrese el codigo solicitado."
    dialog_model.insertByName("lblInstruccion", instruccion_model)

    codigo_label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    codigo_label_model.Name = "lblCodigo"
    codigo_label_model.PositionX = 8
    codigo_label_model.PositionY = 28
    codigo_label_model.Width = 76
    codigo_label_model.Height = 12
    codigo_label_model.Label = "Codigo:"
    dialog_model.insertByName("lblCodigo", codigo_label_model)

    edit_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    edit_model.Name = "txtCodigo"
    edit_model.PositionX = 88
    edit_model.PositionY = 26
    edit_model.Width = 114
    edit_model.Height = 14
    edit_model.Text = ""
    dialog_model.insertByName("txtCodigo", edit_model)

    error_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    error_model.Name = "lblError"
    error_model.PositionX = 8
    error_model.PositionY = 46
    error_model.Width = 194
    error_model.Height = 16
    error_model.MultiLine = True
    error_model.Label = error_texto
    dialog_model.insertByName("lblError", error_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 96
    ok_model.PositionY = 68
    ok_model.Width = 46
    ok_model.Height = 14
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    cancel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_model.Name = "btnCancel"
    cancel_model.PositionX = 146
    cancel_model.PositionY = 68
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
            error_texto = "El codigo no puede estar vacio."
            continue

        return codigo