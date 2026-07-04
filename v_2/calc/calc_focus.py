def enfocar_celda_sin_azul(documento, columna, fila):
    """
    Mueve el recuadro negro de enfoque a una celda sin dejar un bloque azul.
    columna: entero (0 para A, 1 para B, etc.)
    fila: entero (0 para fila 1, 1 para fila 2, etc.)
    """
    controlador = documento.getCurrentController()

    hoja_activa = controlador.ActiveSheet
    num_hoja = hoja_activa.RangeAddress.Sheet

    view_data = controlador.ViewData
    partes_vista = view_data.split(";")

    indice_datos_hoja = num_hoja + 3

    if indice_datos_hoja < len(partes_vista):
        datos_hoja = partes_vista[indice_datos_hoja]

        delimitador = "/" if "/" in datos_hoja else "+"
        sub_partes = datos_hoja.split(delimitador)

        sub_partes[0] = str(columna)
        sub_partes[1] = str(fila)

        partes_vista[indice_datos_hoja] = delimitador.join(sub_partes)

    nuevo_view_data = ";".join(partes_vista)
    controlador.restoreViewData(nuevo_view_data)


def enfocar_ventana_de_calc(documento):
    """
    Devuelve el foco de teclado a la ventana de Calc sin modificar la celda activa.
    """
    controlador = documento.getCurrentController()
    frame = controlador.getFrame()

    ventana = None
    if hasattr(frame, "getComponentWindow"):
        ventana = frame.getComponentWindow()
    if ventana is None and hasattr(frame, "getContainerWindow"):
        ventana = frame.getContainerWindow()

    if ventana is not None and hasattr(ventana, "setFocus"):
        ventana.setFocus()