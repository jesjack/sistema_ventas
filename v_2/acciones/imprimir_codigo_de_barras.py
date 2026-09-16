from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    datos = solicitar_datos_codigo_barras(context)
    if datos is None:
        return

    codigo, copias = datos
    try:
        imprimir_codigo_barras(codigo, numero_copias=copias, density=1, en_segundo_plano=True)
        mostrar_aviso_impresion(context)
        print(f"Codigo de barras enviado a impresion: {codigo} ({copias} copias)")
    except Exception as exc:
        print(f"No se pudo imprimir el codigo de barras: {exc}")
