from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    # "selling" se reasigna (no se muta un objeto compartido), asi que tiene
    # que escribirse via ctx[...] explicito para que main.py vea el cambio --
    # @usar_contexto solo copia valores hacia aca, no los sincroniza de vuelta.
    ctx["selling"] = True
    try:
        with sheet_admin.temporary_unlock():
            return table_manager.sell_items(cart, ventas)
    finally:
        # Sin esto, una excepción en sell_items dejaba "selling" en True y
        # on_enter respondia "Venta en curso" hasta reiniciar el sistema.
        ctx["selling"] = False
