from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    # "selling" se reasigna (no se muta un objeto compartido), asi que tiene
    # que escribirse via ctx[...] explicito para que main.py vea el cambio --
    # @usar_contexto solo copia valores hacia aca, no los sincroniza de vuelta.
    ctx["selling"] = True
    resultado = None
    with sheet_admin.temporary_unlock():
        resultado = table_manager.sell_items(cart, ventas)
    ctx["selling"] = False
    return resultado
