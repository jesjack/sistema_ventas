"""Elegir un código ya registrado, buscándolo por el código o por el nombre del producto."""

from dialogs._base import ConstructorDialogo, EscuchaAccion, EscuchaTexto
from dialogs.varios_codigos import textos_codigos


def _crear_dialogo(uno_context):
    c = ConstructorDialogo(uno_context, "Seleccionar código", 260, 176, x=140, y=60)
    c.etiqueta("lblBuscar", 8, 10, 34, 12, "Buscar:")
    c.campo("txtBuscar", 44, 8, 208, 14)
    # Letra de ancho fijo para que las columnas de textos_codigos() queden alineadas.
    c.agregar("lista", "lstCodigos", 8, 26, 244, 108, Dropdown=False, FontName="Liberation Mono")
    c.etiqueta("lblError", 8, 138, 244, 12, "", multilinea=True)
    c.aceptar_cancelar(156, x_aceptar=152, x_cancelar=202, ancho=50, etiqueta_aceptar="Elegir", cierra_solo=False)
    return c.crear()


def seleccionar_codigo(uno_context, listar_codigos):
    """El texto del código elegido, o None si se cancela. `listar_codigos(filtro)` devuelve los
    CodigoBarras registrados que coinciden (en el código o en el producto)."""
    dialog = _crear_dialogo(uno_context)
    lista = dialog.getControl("lstCodigos")
    buscar = dialog.getControl("txtBuscar")
    aviso = dialog.getControl("lblError").getModel()
    estado = {"mostrados": [], "elegido": None}

    def filtrar():
        try:
            estado["mostrados"] = listar_codigos(str(buscar.getModel().Text))
        except Exception as exc:
            print(f"No se pudieron leer los códigos registrados: {exc}")
            estado["mostrados"] = []
            aviso.Label = "No se pudieron leer los códigos registrados."
        lista.getModel().StringItemList = tuple(textos_codigos(estado["mostrados"]))
        if estado["mostrados"]:
            lista.selectItemPos(0, True)

    def elegir():
        indice = int(lista.getSelectedItemPos())
        if not 0 <= indice < len(estado["mostrados"]):
            aviso.Label = "Seleccione un código de la lista."
            return
        estado["elegido"] = estado["mostrados"][indice].codigo_barras
        dialog.endDialog(1)

    # Se conservan mientras el diálogo esté abierto.
    escuchas = [EscuchaTexto(filtrar), EscuchaAccion(elegir), EscuchaAccion(elegir)]
    buscar.addTextListener(escuchas[0])
    lista.addActionListener(escuchas[1])  # doble clic en un código
    dialog.getControl("btnOk").addActionListener(escuchas[2])

    filtrar()
    buscar.setFocus()
    try:
        dialog.execute()
    finally:
        dialog.dispose()
        del escuchas
    return estado["elegido"]
