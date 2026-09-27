"""Eventos especiales (apertura de caja, fallos...) en la hoja "VENTAS REALIZADAS" y en la base de datos."""


def registrar_evento(ctx, evento, detalle=None, codigo=None):
    with ctx.sheet_admin.temporary_unlock():
        ctx.table_manager.registrar_evento_especial(ctx.ventas, evento, codigo=codigo, detalle=detalle)


def registrar_evento_de_fallo(ctx, evento, detalle, codigo=None):
    # El historial es evidencia: si registrar el fallo también falla
    # (ej. base bloqueada), se avisa por consola pero no se propaga,
    # para no tumbar a quien lo llamó encima del error original.
    try:
        registrar_evento(ctx, evento, detalle=detalle, codigo=codigo)
    except Exception as exc:
        print(f"No se pudo registrar el evento '{evento}' en el historial: {exc}")
