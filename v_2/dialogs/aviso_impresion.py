def _crear_dialogo_aviso(uno_context, mensaje):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 80
    dialog_model.Width = 250
    dialog_model.Height = 92
    dialog_model.Title = "Impresion en curso"

    texto_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    texto_model.Name = "lblMensaje"
    texto_model.PositionX = 8
    texto_model.PositionY = 12
    texto_model.Width = 234
    texto_model.Height = 24
    texto_model.MultiLine = True
    texto_model.Label = mensaje
    dialog_model.insertByName("lblMensaje", texto_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 96
    ok_model.PositionY = 58
    ok_model.Width = 58
    ok_model.Height = 14
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", uno_context)
    dialog.setModel(dialog_model)
    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)
    dialog.createPeer(toolkit, None)
    return dialog


def mostrar_aviso_impresion(uno_context, mensaje="Imprimiendo, espere por favor."):
    dialog = _crear_dialogo_aviso(uno_context, mensaje)
    try:
        dialog.execute()
    finally:
        dialog.dispose()