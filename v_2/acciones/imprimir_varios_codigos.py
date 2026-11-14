from collections import Counter

from dialogs.aviso_error import mostrar_aviso_error
from dialogs.aviso_impresion import mostrar_aviso_impresion
from dialogs.imprimir_varios_codigos import descartar_borrador, solicitar_varios_codigos
from dialogs.varios_codigos import leyenda_con_precio
from hardware.barcode_printer import CODIFICADORES, imprimir_por_piezas, repartir_en_etiquetas, validar_codigo


def ejecutar(ctx):
    # Varios códigos en las mismas etiquetas (3 piezas por etiqueta) para no desperdiciar piezas, y
    # los códigos nuevos se registran en el mismo paso con su producto y su precio.
    datos = solicitar_varios_codigos(
        ctx.context,
        codificadores=list(CODIFICADORES),
        catalogo=ctx.catalogo,
        buscar_codigo=ctx.codigos_barras.obtener_detalle_codigo_barras,
        validar_codigo=validar_codigo,
        listar_codigos=ctx.codigos_barras.listar_codigos_barras,
    )
    if datos is None:
        return

    lista, codificador = datos
    # Primero el registro: si falla (ej. otra sesión registró el mismo código hace un momento), no
    # se imprime nada y no quedan etiquetas de códigos que el escáner no reconocería. La lista
    # sigue guardada en el diálogo para corregirla.
    try:
        ctx.codigos_barras.registrar_codigos_barras(lista.nuevos())
    except Exception as exc:
        print(f"No se pudieron registrar los códigos nuevos: {exc}")
        mostrar_aviso_error(ctx.context, f"No se pudieron registrar los códigos nuevos y no se imprimió nada.\n\n{exc}")
        return
    descartar_borrador()

    piezas = lista.piezas()
    leyendas = {renglon.codigo: leyenda_con_precio(renglon.codigo, renglon.precio) for renglon in lista.renglones}
    # En cuántas etiquetas sale cada código (una etiqueta puede llevar varios).
    etiquetas_por_codigo = Counter(
        codigo for etiqueta in repartir_en_etiquetas(piezas) for codigo in set(etiqueta) if codigo is not None
    )

    def imprimir():
        imprimir_por_piezas(piezas, density=1, en_segundo_plano=True, codificador=codificador, leyendas=leyendas)
        print(f"Varios códigos enviados a impresión: {piezas} ({lista.etiquetas} etiquetas, {codificador})")
        for codigo, cantidad in piezas:
            try:
                ctx.codigos_barras.registrar_impresion(
                    codigo, etiquetas_por_codigo[codigo], horizontal=False, codificador=codificador, piezas=cantidad
                )
            except Exception as exc:
                print(f"No se pudo registrar la impresión del código {codigo}: {exc}")

    try:
        imprimir()
    except Exception as exc:
        print(f"No se pudieron imprimir los códigos: {exc}")
        mostrar_aviso_error(ctx.context, f"Los códigos quedaron registrados, pero no se pudieron imprimir.\n\n{exc}")
        return
    mostrar_aviso_impresion(ctx.context, reintentar=imprimir)
