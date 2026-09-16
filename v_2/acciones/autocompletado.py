from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    abrir_editor_catalogo_autocompletado(
        context,
        ventas_service=table_manager.ventas_service,
    )
