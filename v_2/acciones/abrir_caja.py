from nucleo.caja import abrir_caja


def ejecutar(ctx):
    if abrir_caja(ctx, detalle_ok="Se abrió la caja desde el botón de la hoja."):
        print("Caja abierta desde el boton.")
