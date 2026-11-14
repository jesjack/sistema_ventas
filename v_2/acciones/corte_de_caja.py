"""Corte de caja: abre el cajón, pide el cambio que se queda en la caja y desde ahí la tabla de
ventas empieza en limpio, con ese cambio como primeras filas para que su total cuadre con el
dinero de la caja."""

from dialogs.corte_caja import confirmar_corte, solicitar_cambio_corte
from hardware.ticket_printer import imprimir_ticket_corte
from nucleo.caja import abrir_caja
from services.identidad import obtener_usuario_actual


def ejecutar(ctx):
    abrir_caja(
        ctx,
        detalle_ok="Se abrió la caja para hacer un corte de caja.",
        detalle_fallo="Se pidió un corte de caja, pero no se pudo abrir la caja: {exc}",
    )

    cambio = solicitar_cambio_corte(ctx.context)
    if cambio is None or not confirmar_corte(ctx.context, cambio):
        print("Corte de caja cancelado.")
        return

    with ctx.sheet_admin.temporary_unlock():
        ctx.table_manager.cash_cut(ctx.ventas, cambio)
        ctx.ventas.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)
    print("Corte de caja hecho.")

    try:
        imprimir_ticket_corte(cambio, usuario=obtener_usuario_actual())
    except Exception as exc:
        print(f"No se pudo imprimir el ticket del corte de caja: {exc}")
