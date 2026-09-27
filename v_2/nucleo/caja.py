"""Abrir la caja registradora: una sola vía para el botón y para el código autorizado del cobro."""

from hardware.ticket_printer import TicketPrinter
from nucleo.historial import registrar_evento, registrar_evento_de_fallo


def abrir_caja(ctx, detalle_ok, codigo=None, detalle_fallo=None, crear_impresora=TicketPrinter):
    """Abre el cajón y deja constancia. Devuelve True si se abrió.

    Solo se audita la apertura si de verdad ocurrió: un fallo de la impresora no debe dejar un
    evento que diga que se abrió. El fallo se audita solo si se da `detalle_fallo`
    (puede llevar "{exc}" para el motivo)."""
    try:
        crear_impresora().open_cash_drawer()
    except Exception as exc:
        print(f"No se pudo abrir la caja: {exc}")
        if detalle_fallo is not None:
            registrar_evento_de_fallo(ctx, "FALLO AL ABRIR CAJA", detalle_fallo.format(exc=exc), codigo=codigo)
        return False

    registrar_evento(ctx, "APERTURA DE CAJA", detalle=detalle_ok, codigo=codigo)
    return True
