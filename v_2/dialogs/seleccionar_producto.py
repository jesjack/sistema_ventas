"""Elegir un producto del catálogo de autocompletado, con búsqueda y, si no está, registrarlo ahí
mismo y quedarse con él."""

from dialogs._base import ConstructorDialogo, EscuchaAccion, EscuchaTexto
from dialogs.varios_codigos import filtrar_productos
from services.catalogo_service import ProductoDuplicado, formatear_nombre


def _crear_dialogo(uno_context):
    c = ConstructorDialogo(uno_context, "Seleccionar producto", 260, 214, x=140, y=60)
    c.etiqueta("lblBuscar", 8, 10, 34, 12, "Buscar:")
    c.campo("txtBuscar", 44, 8, 208, 14)
    c.agregar("lista", "lstProductos", 8, 26, 244, 100, Dropdown=False)
    c.etiqueta("lblNuevo", 8, 134, 244, 12, "¿No está en la lista? Escríbalo aquí para registrarlo:")
    c.campo("txtNuevo", 8, 148, 160, 14)
    c.boton("btnRegistrar", 172, 148, 80, 14, "Registrar y elegir")
    c.etiqueta("lblError", 8, 168, 244, 20, "", multilinea=True)
    c.aceptar_cancelar(194, x_aceptar=152, x_cancelar=202, ancho=50, etiqueta_aceptar="Elegir", cierra_solo=False)
    return c.crear()


def seleccionar_producto(uno_context, catalogo):
    """(producto_id, nombre) del producto elegido o recién registrado, o None si se cancela."""
    dialog = _crear_dialogo(uno_context)
    lista = dialog.getControl("lstProductos")
    buscar = dialog.getControl("txtBuscar")
    nuevo = dialog.getControl("txtNuevo")
    aviso = dialog.getControl("lblError").getModel()
    estado = {"mostrados": [], "elegido": None}

    try:
        productos = catalogo.listar_catalogo_autocompletado()
    except Exception as exc:
        print(f"No se pudo leer el catálogo: {exc}")
        productos = []
        aviso.Label = "No se pudo leer el catálogo; puede registrar el producto abajo."

    def filtrar():
        estado["mostrados"] = filtrar_productos(productos, buscar.getModel().Text)
        lista.getModel().StringItemList = tuple(formatear_nombre(nombre) for _id, nombre in estado["mostrados"])
        if estado["mostrados"]:
            lista.selectItemPos(0, True)

    def elegir_de_la_lista():
        indice = int(lista.getSelectedItemPos())
        if not 0 <= indice < len(estado["mostrados"]):
            aviso.Label = "Seleccione un producto de la lista."
            return
        estado["elegido"] = estado["mostrados"][indice]
        dialog.endDialog(1)

    def registrar():
        nombre = str(nuevo.getModel().Text).strip().lower()
        if not nombre:
            aviso.Label = "Escriba el nombre del producto nuevo."
            return
        try:
            producto_id = catalogo.agregar_producto_autocompletado(nombre)
        except ProductoDuplicado:
            # Ya existía (quizá con otras mayúsculas): se elige ese mismo.
            existente = next((p for p in catalogo.listar_catalogo_autocompletado() if p[1].lower() == nombre), None)
            if existente is None:
                aviso.Label = "Ese producto ya existe en el catálogo."
                return
            estado["elegido"] = existente
        except Exception as exc:
            print(f"No se pudo registrar el producto '{nombre}': {exc}")
            aviso.Label = f"No se pudo registrar el producto: {exc}"
            return
        else:
            estado["elegido"] = (producto_id, nombre)
        dialog.endDialog(1)

    # Se conservan mientras el diálogo esté abierto.
    escuchas = [EscuchaTexto(filtrar), EscuchaAccion(elegir_de_la_lista), EscuchaAccion(elegir_de_la_lista),
                EscuchaAccion(registrar)]
    buscar.addTextListener(escuchas[0])
    lista.addActionListener(escuchas[1])  # doble clic en un producto
    dialog.getControl("btnOk").addActionListener(escuchas[2])
    dialog.getControl("btnRegistrar").addActionListener(escuchas[3])

    filtrar()
    buscar.setFocus()
    try:
        dialog.execute()
    finally:
        dialog.dispose()
        del escuchas
    return estado["elegido"]
