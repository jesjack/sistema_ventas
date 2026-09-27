from ui.lista_codigos_barras import abrir_lista_codigos_barras


def ejecutar(ctx):
    abrir_lista_codigos_barras(ctx.context, ctx.codigos_barras)
