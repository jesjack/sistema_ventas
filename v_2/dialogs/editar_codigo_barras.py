"""Editar un código de barras registrado: su texto, su producto y su precio."""

from dialogs._base import ConstructorDialogo, EscuchaAccion
from dialogs.formato import formatear_precio
from dialogs.seleccionar_producto import seleccionar_producto
from dialogs.varios_codigos import leer_precio, validar_codigo_escrito
from services.catalogo_service import formatear_nombre
from services.codigos_barras_service import CodigoDuplicado

AVISO_ETIQUETAS = "Las etiquetas ya impresas no cambian: si cambia el código o el precio, vuelva a imprimirlas."


def _crear_dialogo(uno_context, codigo):
    c = ConstructorDialogo(uno_context, "Editar código de barras", 250, 150, x=130, y=70)
    c.etiqueta("lblCodigo", 8, 10, 50, 12, "Código:")
    c.campo("txtCodigo", 62, 8, 80, 14, texto=codigo.codigo_barras)
    c.etiqueta("lblProducto", 8, 28, 50, 12, "Producto:")
    c.campo("txtProducto", 62, 26, 120, 14, texto=formatear_nombre(codigo.producto), ReadOnly=True)
    c.boton("btnCambiar", 186, 26, 56, 14, "Cambiar...")
    c.etiqueta("lblPrecio", 8, 46, 50, 12, "Precio:")
    c.campo("txtPrecio", 62, 44, 80, 14, texto=f"{codigo.precio_venta:.2f}")
    c.etiqueta("lblAviso", 8, 64, 234, 20, AVISO_ETIQUETAS, multilinea=True)
    c.etiqueta("lblError", 8, 88, 234, 32, "", multilinea=True)
    c.aceptar_cancelar(128, x_aceptar=142, x_cancelar=196, ancho=46, etiqueta_aceptar="Guardar", cierra_solo=False)
    return c.crear()


def editar_codigo_barras(uno_context, codigo, codigos_service, catalogo):
    """Abre el diálogo para `codigo` (un CodigoBarras) y guarda los cambios. True si se guardó."""
    dialog = _crear_dialogo(uno_context, codigo)
    campo_codigo = dialog.getControl("txtCodigo")
    campo_producto = dialog.getControl("txtProducto").getModel()
    campo_precio = dialog.getControl("txtPrecio")
    aviso = dialog.getControl("lblError").getModel()
    producto = {"id": codigo.producto_id}

    def cambiar_producto():
        elegido = seleccionar_producto(uno_context, catalogo)
        if elegido is not None:
            producto["id"] = elegido[0]
            campo_producto.Text = formatear_nombre(elegido[1])

    def guardar():
        texto = str(campo_codigo.getModel().Text).strip()
        try:
            # Un código viejo más largo que lo que se imprime se puede dejar como está; uno nuevo no.
            nuevo = texto if texto == codigo.codigo_barras else validar_codigo_escrito(texto, None)
            precio = leer_precio(campo_precio.getModel().Text)
        except ValueError as exc:
            aviso.Label = str(exc)
            return

        try:
            codigos_service.actualizar_codigo_barras(codigo.id, nuevo, producto["id"], precio)
        except CodigoDuplicado:
            aviso.Label = f"Ya hay otro código registrado como «{nuevo}»."
            return
        except Exception as exc:
            print(f"No se pudo guardar el código '{codigo.codigo_barras}': {exc}")
            aviso.Label = f"No se pudo guardar: {exc}"
            return

        print(
            f"Codigo de barras editado: {codigo.codigo_barras} -> {nuevo}, producto {codigo.producto_id} -> "
            f"{producto['id']}, precio {formatear_precio(codigo.precio_venta)} -> {formatear_precio(precio)}"
        )
        dialog.endDialog(1)

    # Se conservan mientras el diálogo esté abierto.
    escuchas = [EscuchaAccion(cambiar_producto), EscuchaAccion(guardar)]
    dialog.getControl("btnCambiar").addActionListener(escuchas[0])
    dialog.getControl("btnOk").addActionListener(escuchas[1])

    campo_precio.setFocus()
    try:
        return dialog.execute() == 1
    finally:
        dialog.dispose()
        del escuchas
