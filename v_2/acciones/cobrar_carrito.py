def ejecutar(ctx):
    ctx.selling = True
    try:
        with ctx.sheet_admin.temporary_unlock():
            return ctx.table_manager.sell_items(ctx.cart, ctx.ventas)
    finally:
        # Sin esto, una excepción en sell_items dejaba "selling" en True y
        # on_enter respondia "Venta en curso" hasta reiniciar el sistema.
        ctx.selling = False
