def _parse_copias(texto):
    if texto is None:
        raise ValueError("copias vacias")

    limpio = str(texto).strip()
    if not limpio:
        raise ValueError("copias vacias")

    copias = int(limpio)
    return copias


def _crear_dialogo(uno_context, error_texto=""):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 80
    dialog_model.Width = 250
    dialog_model.Height = 124
    dialog_model.Title = "Imprimir codigo de barras"

    instruccion_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    instruccion_model.Name = "lblInstruccion"
    instruccion_model.PositionX = 8
    instruccion_model.PositionY = 8
    instruccion_model.Width = 234
    instruccion_model.Height = 12
    instruccion_model.Label = "Ingrese el texto del codigo y la cantidad de copias."
    dialog_model.insertByName("lblInstruccion", instruccion_model)

    texto_label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    texto_label_model.Name = "lblTexto"
    texto_label_model.PositionX = 8
    texto_label_model.PositionY = 26
    texto_label_model.Width = 92
    texto_label_model.Height = 12
    texto_label_model.Label = "Codigo (max 6):"
    dialog_model.insertByName("lblTexto", texto_label_model)

    texto_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    texto_model.Name = "txtCodigo"
    texto_model.PositionX = 104
    texto_model.PositionY = 24
    texto_model.Width = 134
    texto_model.Height = 14
    texto_model.Text = ""
    texto_model.MaxTextLen = 6
    dialog_model.insertByName("txtCodigo", texto_model)

    copias_label_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    copias_label_model.Name = "lblCopias"
    copias_label_model.PositionX = 8
    copias_label_model.PositionY = 46
    copias_label_model.Width = 92
    copias_label_model.Height = 12
    copias_label_model.Label = "Copias (1 a 5):"
    dialog_model.insertByName("lblCopias", copias_label_model)

    copias_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    copias_model.Name = "txtCopias"
    copias_model.PositionX = 104
    copias_model.PositionY = 44
    copias_model.Width = 40
    copias_model.Height = 14
    copias_model.Text = "1"
    copias_model.MaxTextLen = 1
    dialog_model.insertByName("txtCopias", copias_model)

    error_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    error_model.Name = "lblError"
    error_model.PositionX = 8
    error_model.PositionY = 64
    error_model.Width = 234
    error_model.Height = 22
    error_model.MultiLine = True
    error_model.Label = error_texto
    dialog_model.insertByName("lblError", error_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 148
    ok_model.PositionY = 92
    ok_model.Width = 46
    ok_model.Height = 14
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    cancel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_model.Name = "btnCancel"
    cancel_model.PositionX = 198
    cancel_model.PositionY = 92
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


def solicitar_datos_codigo_barras(uno_context):
    error_texto = ""

    while True:
        dialog = _crear_dialogo(uno_context, error_texto)
        try:
            result = dialog.execute()
            if result != 1:
                return None

            texto = dialog.getControl("txtCodigo").getModel().Text
            copias_texto = dialog.getControl("txtCopias").getModel().Text
        finally:
            dialog.dispose()

        codigo = str(texto).strip()
        if not codigo:
            error_texto = "El codigo no puede estar vacio."
            continue

        if len(codigo) > 6:
            error_texto = "El codigo debe tener como maximo 6 caracteres."
            continue

        try:
            copias = _parse_copias(copias_texto)
        except (TypeError, ValueError):
            error_texto = "La cantidad de copias debe ser un numero entero entre 1 y 5."
            continue

        if copias < 1 or copias > 5:
            error_texto = "La cantidad de copias debe estar entre 1 y 5."
            continue

        return codigo, copias