from dialogs.aviso_impresion import mostrar_aviso_impresion
from dialogs.imprimir_codigo_barras import solicitar_datos_codigo_barras
from hardware.barcode_printer import imprimir_codigo_barras


def ejecutar(ctx):
    # Mientras se escribe el código, el diálogo muestra el producto y el precio si ya está registrado.
    datos = solicitar_datos_codigo_barras(
        ctx.context,
        buscar_codigo=ctx.codigos_barras.obtener_detalle_codigo_barras,
    )
    if datos is None:
        return

    codigo, copias = datos
    try:
        imprimir_codigo_barras(codigo, numero_copias=copias, density=1, en_segundo_plano=True)
        mostrar_aviso_impresion(ctx.context)
        print(f"Codigo de barras enviado a impresion: {codigo} ({copias} copias)")
    except Exception as exc:
        print(f"No se pudo imprimir el codigo de barras: {exc}")
