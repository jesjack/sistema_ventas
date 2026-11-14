"""Diálogo del corte de caja: cuántos billetes y monedas de cada denominación se dejan de cambio."""

from dialogs._base import ACEPTAR, CANCELAR, ConstructorDialogo, EscuchaAccion, EscuchaTexto
from services.corte_caja import (
    BILLETE,
    DENOMINACIONES,
    leer_cambio,
    leer_cantidad,
    texto_denominacion,
    total_del_cambio,
)

ANCHO, ALTO = 262, 196
ALTO_RENGLON = 16


def _nombre_campo(indice):
    return f"txtCantidad{indice}"


def _nombre_subtotal(indice):
    return f"lblSubtotal{indice}"


def _crear_dialogo(uno_context):
    c = ConstructorDialogo(uno_context, "Corte de caja", ANCHO, ALTO, x=120, y=40)
    c.etiqueta(
        "lblInstruccion", 8, 6, 246, 20,
        "Escriba cuántas piezas de cada billete y moneda se quedan en la caja como cambio. "
        "Lo que no haya, déjelo vacío.",
        multilinea=True,
    )
    c.etiqueta("lblBilletes", 8, 30, 120, 12, "Billetes", FontWeight=150)
    c.etiqueta("lblMonedas", 136, 30, 120, 12, "Monedas", FontWeight=150)

    renglones = {}
    for indice, (tipo, denominacion) in enumerate(DENOMINACIONES):
        renglon = renglones.setdefault(tipo, 0)
        renglones[tipo] += 1
        x = 8 if tipo == BILLETE else 136
        y = 46 + renglon * ALTO_RENGLON
        c.etiqueta(f"lblDenominacion{indice}", x, y + 2, 30, 12, texto_denominacion(denominacion), Align=2)
        c.campo(_nombre_campo(indice), x + 34, y, 30, 14, max_len=4)
        c.etiqueta(_nombre_subtotal(indice), x + 68, y + 2, 52, 12, "")

    c.etiqueta("lblTotal", 8, 146, 246, 12, "", FontWeight=150)
    c.etiqueta("lblError", 8, 158, 246, 18, "", multilinea=True, TextColor=0xB00000)
    c.boton("btnCortar", 150, 178, 56, 14, "Hacer corte", por_defecto=True)
    c.boton("btnCancel", 210, 178, 46, 14, "Cancelar", CANCELAR)
    return c.crear()


def solicitar_cambio_corte(uno_context):
    """[(tipo, denominacion, cantidad), ...] con lo que se escribió, o None si se cancela."""
    dialog = _crear_dialogo(uno_context)
    control = dialog.getControl
    resultado = {}

    def textos():
        return [str(control(_nombre_campo(i)).getModel().Text) for i in range(len(DENOMINACIONES))]

    def actualizar():
        total = 0.0
        for indice, ((_tipo, denominacion), texto) in enumerate(zip(DENOMINACIONES, textos())):
            try:
                cantidad = leer_cantidad(texto)
            except ValueError:
                control(_nombre_subtotal(indice)).getModel().Label = "¿?"
                continue
            subtotal = denominacion * cantidad
            total += subtotal
            control(_nombre_subtotal(indice)).getModel().Label = f"= ${subtotal:,.2f}" if cantidad else ""
        control("lblTotal").getModel().Label = f"Total de cambio: ${total:,.2f}"
        control("lblError").getModel().Label = ""

    def cortar():
        try:
            cambio = leer_cambio(textos())
        except ValueError as exc:
            control("lblError").getModel().Label = str(exc)
            return
        resultado["cambio"] = cambio
        dialog.endDialog(ACEPTAR)

    for indice in range(len(DENOMINACIONES)):
        control(_nombre_campo(indice)).addTextListener(EscuchaTexto(actualizar))
    control("btnCortar").addActionListener(EscuchaAccion(cortar))
    actualizar()

    try:
        if dialog.execute() != ACEPTAR:
            return None
    finally:
        dialog.dispose()
    return resultado.get("cambio")


def confirmar_corte(uno_context, cambio):
    """Último aviso antes de hacer el corte. True si se confirma; Enter elige "Regresar"."""
    c = ConstructorDialogo(uno_context, "Confirmar corte de caja", 230, 84, x=140, y=120)
    c.etiqueta(
        "lblAviso", 8, 8, 214, 44,
        f"Se hará el corte con ${total_del_cambio(cambio):,.2f} de cambio en la caja.\n"
        "Las ventas de hoy hechas hasta ahora dejarán de verse en la tabla (siguen guardadas y "
        "se pueden revisar con VER VENTAS).",
        multilinea=True,
    )
    c.boton("btnNo", 8, 62, 80, 14, "Regresar", CANCELAR, por_defecto=True)
    c.boton("btnSi", 142, 62, 80, 14, "Hacer el corte", ACEPTAR)
    dialog = c.crear()
    try:
        return dialog.execute() == ACEPTAR
    finally:
        dialog.dispose()
