from dialogs.aviso_impresion import mostrar_aviso_impresion
from dialogs.imprimir_codigo_barras import solicitar_datos_codigo_barras
from hardware.barcode_printer import CODIFICADORES, imprimir_codigo_barras, imprimir_etiqueta_prueba, validar_codigo


def ejecutar(ctx):
    # Mientras se escribe el código, el diálogo muestra el producto y el precio si ya está registrado.
    datos = solicitar_datos_codigo_barras(
        ctx.context,
        codificadores=list(CODIFICADORES),
        buscar_codigo=ctx.codigos_barras.obtener_detalle_codigo_barras,
        validar_codigo=validar_codigo,
        imprimir_prueba=lambda: imprimir_etiqueta_prueba(density=1, en_segundo_plano=True),
    )
    if datos is None:
        return

    codigo, copias, horizontal, codificador = datos
    try:
        imprimir_codigo_barras(
            codigo, numero_copias=copias, density=1, en_segundo_plano=True,
            horizontal=horizontal, codificador=codificador,
        )
        mostrar_aviso_impresion(ctx.context)
        print(f"Codigo de barras enviado a impresion: {codigo} ({copias} copias, {codificador})")
    except Exception as exc:
        print(f"No se pudo imprimir el codigo de barras: {exc}")
