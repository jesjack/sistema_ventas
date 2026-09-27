"""Textos con los que los diálogos describen un código de barras registrado (sin UNO, para poder probarlos)."""

from datetime import datetime

TEXTO_INICIAL = "Escribe el código: si ya está registrado verás aquí su producto y precio."
TEXTO_NO_REGISTRADO = "Código no registrado."
TEXTO_SIN_CONSULTA = "No se pudo consultar los códigos registrados."


def formatear_precio(precio):
    return f"${float(precio):.2f}"


def formatear_fecha_registro(creado_en):
    """"2026-09-09 19:55:20" -> "09-09-2026 19:55" (lo que no se entienda se deja tal cual)."""
    if not creado_en:
        return ""
    try:
        return datetime.strptime(str(creado_en), "%Y-%m-%d %H:%M:%S").strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return str(creado_en)


def describir_codigo(detalle):
    """Varias lineas con todo lo que se sabe del codigo; `detalle` es un CodigoBarras o None."""
    if detalle is None:
        return TEXTO_NO_REGISTRADO

    lineas = [
        "Código ya registrado.",
        f"Producto: {detalle.producto}",
        f"Precio de venta: {formatear_precio(detalle.precio_venta)}",
    ]
    fecha = formatear_fecha_registro(detalle.creado_en)
    if fecha:
        lineas.append(f"Registrado el: {fecha}")
    if detalle.otros_codigos:
        lineas.append(f"Otros códigos de este producto: {detalle.otros_codigos}")
    return "\n".join(lineas)
