def ejecutar(ctx):
    print("Limpiando carrito...")
    with ctx.sheet_admin.temporary_unlock():
        ctx.cart.clear()
