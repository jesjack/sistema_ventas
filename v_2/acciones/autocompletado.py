from ui.catalogo_autocompletado import abrir_editor_catalogo_autocompletado


def ejecutar(ctx):
    abrir_editor_catalogo_autocompletado(ctx.context, catalogo=ctx.catalogo)
