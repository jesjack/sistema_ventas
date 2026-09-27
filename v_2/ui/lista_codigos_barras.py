"""Ventana con los códigos de barras registrados: código, producto, precio y cuándo se registró.
Se filtra mientras se escribe en "Buscar" (por código o por nombre del producto)."""

from dialogs._base import ConstructorDialogo, EscuchaTexto, mostrar_y_cerrar
from dialogs.formato import formatear_fecha_registro, formatear_precio

# (título, ancho): deben sumar un poco menos que el ancho de la tabla (ANCHO - 16) para dejar sitio
# a la barra vertical; si se pasan, aparece una barra horizontal.
COLUMNAS = (("Código", 66), ("Producto", 138), ("Precio", 46), ("Registrado", 76))
ANCHO, ALTO = 372, 226


def filas_de(codigos):
    return [
        (c.codigo_barras, c.producto, formatear_precio(c.precio_venta), formatear_fecha_registro(c.creado_en))
        for c in codigos
    ]


def texto_conteo(mostrados, total):
    if mostrados == total:
        return f"{total} código{'s' if total != 1 else ''}"
    return f"{mostrados} de {total} códigos"


def _crear_dialogo(uno_context):
    c = ConstructorDialogo(uno_context, "Códigos de barras registrados", ANCHO, ALTO, x=90, y=50)
    c.etiqueta("lblBuscar", 8, 10, 34, 12, "Buscar:")
    c.campo("txtBuscar", 44, 8, 170, 14)
    c.etiqueta("lblConteo", 222, 10, 142, 12, "", Align=2)

    tabla = c.modelo.createInstance("com.sun.star.awt.grid.UnoControlGridModel")
    tabla.Name = "tabla"
    tabla.PositionX, tabla.PositionY, tabla.Width, tabla.Height = 8, 28, ANCHO - 16, ALTO - 28 - 30
    columnas = c.smgr.createInstanceWithContext("com.sun.star.awt.grid.DefaultGridColumnModel", uno_context)
    for titulo, ancho in COLUMNAS:
        columna = columnas.createColumn()
        columna.Title = titulo
        columna.ColumnWidth = ancho
        columna.Flexibility = 0
        columnas.addColumn(columna)
    tabla.ColumnModel = columnas
    tabla.GridDataModel = c.smgr.createInstanceWithContext("com.sun.star.awt.grid.DefaultGridDataModel", uno_context)
    tabla.ShowRowHeader = False
    c.modelo.insertByName("tabla", tabla)

    c.boton("btnCerrar", ANCHO - 58, ALTO - 22, 50, 14, "Cerrar", 1, por_defecto=True)
    return c.crear()


def abrir_lista_codigos_barras(uno_context, codigos_service):
    dialog = _crear_dialogo(uno_context)
    datos = dialog.getControl("tabla").getModel().GridDataModel
    conteo = dialog.getControl("lblConteo").getModel()
    campo = dialog.getControl("txtBuscar")

    def actualizar():
        try:
            todos = codigos_service.listar_codigos_barras()
            filtro = str(campo.getModel().Text).strip()
            mostrados = codigos_service.listar_codigos_barras(filtro) if filtro else todos
        except Exception as exc:
            print(f"No se pudo leer la lista de códigos de barras: {exc}")
            datos.removeAllRows()
            conteo.Label = "No se pudo consultar la lista."
            return

        datos.removeAllRows()
        for fila in filas_de(mostrados):
            datos.addRow("", fila)
        conteo.Label = texto_conteo(len(mostrados), len(todos))

    escucha = EscuchaTexto(actualizar)  # se conserva mientras la ventana esté abierta
    campo.addTextListener(escucha)
    actualizar()
    campo.setFocus()
    mostrar_y_cerrar(dialog)
    del escucha
