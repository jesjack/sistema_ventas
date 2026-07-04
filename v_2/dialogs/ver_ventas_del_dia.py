from __future__ import annotations

from dialogs.seleccionar_fecha_ventas import formatear_fecha_ventas


def _formatear_fila(venta):
    hora, producto, precio, cantidad, subtotal = venta
    precio_texto = "" if precio == "" else f"{float(precio):.2f}"
    cantidad_texto = "" if cantidad == "" else str(cantidad)
    subtotal_texto = "" if subtotal == "" else f"{float(subtotal):.2f}"
    return f"{hora} | {producto} | {precio_texto} | {cantidad_texto} | {subtotal_texto}"


def _crear_dialogo(uno_context, fecha_iso, ventas):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 120
    dialog_model.PositionY = 70
    dialog_model.Width = 420
    dialog_model.Height = 260
    dialog_model.Title = f"Ventas del {formatear_fecha_ventas(fecha_iso)}"

    lbl = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    lbl.Name = "lblTitulo"
    lbl.PositionX = 8
    lbl.PositionY = 8
    lbl.Width = 404
    lbl.Height = 12
    lbl.Label = f"Ventas del dia {formatear_fecha_ventas(fecha_iso)}"
    dialog_model.insertByName("lblTitulo", lbl)

    list_model = dialog_model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
    list_model.Name = "lstVentas"
    list_model.PositionX = 8
    list_model.PositionY = 24
    list_model.Width = 404
    list_model.Height = 194
    list_model.Dropdown = False
    list_model.MultiSelection = False
    list_model.StringItemList = tuple(_formatear_fila(venta) for venta in ventas) or (
        "No hay ventas para la fecha seleccionada.",
    )
    dialog_model.insertByName("lstVentas", list_model)

    btn_cerrar = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    btn_cerrar.Name = "btnCerrar"
    btn_cerrar.PositionX = 356
    btn_cerrar.PositionY = 224
    btn_cerrar.Width = 56
    btn_cerrar.Height = 14
    btn_cerrar.Label = "Cerrar"
    btn_cerrar.PushButtonType = 1
    dialog_model.insertByName("btnCerrar", btn_cerrar)

    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", uno_context)
    dialog.setModel(dialog_model)
    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)
    dialog.createPeer(toolkit, None)
    return dialog


def abrir_ventana_ventas_del_dia(uno_context, ventas_service, fecha_iso):
    ventas = ventas_service.obtener_ventas(fecha=fecha_iso)
    dialog = _crear_dialogo(uno_context, fecha_iso, ventas)
    try:
        dialog.execute()
    finally:
        dialog.dispose()