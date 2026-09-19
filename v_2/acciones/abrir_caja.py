from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    try:
        printer = TicketPrinter()
        printer.open_cash_drawer()
        print("Caja abierta desde el boton.")
    except Exception as exc:
        print(f"No se pudo abrir la caja: {exc}")
        return

    with sheet_admin.temporary_unlock():
        table_manager.registrar_evento_especial(
            ventas,
            "APERTURA DE CAJA",
            detalle="Se abrió la caja desde el botón de la hoja.",
        )
