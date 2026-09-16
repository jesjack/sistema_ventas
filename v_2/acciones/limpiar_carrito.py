from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    print("Limpiando carrito...")
    with sheet_admin.temporary_unlock():
        cart.clear()
