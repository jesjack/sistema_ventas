"""El cambio que se deja en la caja al hacer un corte: qué billetes y monedas se cuentan y cómo se
leen y se muestran (sin UNO ni base de datos, para poder probarlo)."""

BILLETE = "BILLETE"
MONEDA = "MONEDA"

# En el orden en que aparecen en el diálogo, en el ticket y en la tabla de ventas.
DENOMINACIONES = (
    (BILLETE, 500),
    (BILLETE, 200),
    (BILLETE, 100),
    (BILLETE, 50),
    (BILLETE, 20),
    (MONEDA, 20),
    (MONEDA, 10),
    (MONEDA, 5),
    (MONEDA, 2),
    (MONEDA, 1),
    (MONEDA, 0.5),
)


def texto_denominacion(denominacion):
    """500 -> "$500", 0.5 -> "$0.50"."""
    denominacion = float(denominacion)
    if denominacion.is_integer():
        return f"${int(denominacion)}"
    return f"${denominacion:.2f}"


def producto_de_cambio(tipo):
    """Lo que dice la columna PRODUCTO de la tabla de ventas en una fila del cambio."""
    return f"CAMBIO: {tipo}"


def leer_cantidad(texto):
    """Cuántas piezas de una denominación se escribieron: vacío es 0. ValueError si no es un
    entero >= 0."""
    limpio = str(texto or "").strip()
    if not limpio:
        return 0
    cantidad = int(limpio)
    if cantidad < 0:
        raise ValueError("cantidad negativa")
    return cantidad


def total_del_cambio(cambio):
    """`cambio`: [(tipo, denominacion, cantidad), ...]."""
    return sum(float(denominacion) * int(cantidad) for _tipo, denominacion, cantidad in cambio)


def resumen_del_cambio(cambio):
    """Una línea para el historial: "2 x BILLETE $500, 3 x MONEDA $10 = $1,030.00"."""
    partes = [
        f"{int(cantidad)} x {tipo} {texto_denominacion(denominacion)}"
        for tipo, denominacion, cantidad in cambio
        if int(cantidad)
    ]
    total = f"${total_del_cambio(cambio):,.2f}"
    return f"{', '.join(partes)} = {total}" if partes else f"Sin cambio ({total})"


def leer_cambio(textos):
    """`textos`: lo escrito para cada denominación, en el orden de DENOMINACIONES. Devuelve
    [(tipo, denominacion, cantidad), ...] o lanza ValueError con un mensaje para el usuario."""
    cambio = []
    for (tipo, denominacion), texto in zip(DENOMINACIONES, textos):
        try:
            cantidad = leer_cantidad(texto)
        except ValueError:
            raise ValueError(
                f"La cantidad de {tipo.lower()}s de {texto_denominacion(denominacion)} no es válida: "
                "escriba cuántas piezas hay (un número entero) o déjelo vacío."
            ) from None
        cambio.append((tipo, denominacion, cantidad))
    return cambio
