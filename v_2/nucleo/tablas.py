"""Las tres tablas de la hoja (entrada, carrito, ventas): se reutilizan si prebake_ventas.py ya las
horneó antes de abrir soffice, o se construyen en vivo con UNO."""

from datetime import datetime
from pathlib import Path

from table_modules import attach_existing, create_table


def hoja_desactualizada(ruta_ods, ventas_rows, ahora=None):
    """True si `ruta_ods` (el main.ods que prebake_ventas.py escribió) es más viejo que la
    última fila de `ventas_rows` (ventas + eventos de HOY, ya ordenados por hora, tal como los
    da VentasService.obtener_ventas()).

    2026-09-24: main.ods se abre a veces sin pasar por open_system.sh (que es el único que
    prehornea) -- un acceso directo viejo o "Abrir reciente" de LibreOffice también disparan el
    macro que lanza main.py, así que el sistema arranca con normalidad pero sirve datos de
    ventas de HORAS antes, sin ningún aviso: el único chequeo que había (el título "VENTAS
    REALIZADAS" en la celda) sigue siendo cierto para siempre desde el primer prehorneado
    exitoso, prehornee o no la sesión que se está abriendo. Esto compara contra la última
    actividad real en vez de fiarse del título."""
    if not ventas_rows:
        return False

    ahora = ahora or datetime.now()
    try:
        ultima_hora = datetime.strptime(ventas_rows[-1][0], "%H:%M:%S").time()
        mtime_ods = datetime.fromtimestamp(Path(ruta_ods).stat().st_mtime)
    except (OSError, ValueError):
        # Sin poder comparar (archivo inaccesible, hora con un formato inesperado...), se
        # confía en el título como antes: mejor eso que reconstruir en vivo sin necesidad.
        return False

    return mtime_ods < datetime.combine(ahora.date(), ultima_hora)


def preparar_tablas(hoja, sheet_admin, table_manager, ventas_rows, ruta_ods=None):
    """Devuelve (tabla_entrada, cart, ventas)."""
    # Chequeo minimo de sanidad: si el titulo de "ventas" ya esta en la hoja,
    # asumimos que prebake_ventas.py corrio antes de abrir soffice y nos
    # enganchamos a lo ya renderizado en vez de reconstruirlo con UNO.
    prebaked = False
    try:
        prebaked = hoja.getCellByPosition(6, 1).String == "VENTAS REALIZADAS"
    except Exception:
        prebaked = False

    if prebaked and ruta_ods is not None and hoja_desactualizada(ruta_ods, ventas_rows):
        print(
            "La hoja pre-horneada esta desactualizada (se abrio main.ods sin pasar por "
            "open_system.sh): reconstruyendo en vivo con las ventas de hoy."
        )
        prebaked = False

    with sheet_admin.temporary_unlock():
        if prebaked:
            try:
                tabla_entrada = attach_existing(
                    hoja, 1, 1, ["PRODUCTO", "PRECIO", "C."],
                    header_color=0x9B111E, title="INGRESE LOS DATOS",
                    rows=[("", "", 1)],
                )
                cart = attach_existing(
                    hoja, 1, 5, ["PRODUCTO", "PRECIO", "C.", "SUBTOTAL"],
                    header_color=0x1CA9C9, title="CARRITO DE COMPRA",
                    show_total=True, total_label_span=2,
                    placeholder="EL CARRITO ESTÁ VACÍO", rows=[],
                )
                ventas = attach_existing(
                    hoja, 6, 1, ["HORA", "PRODUCTO", "PRECIO", "C.", "SUBTOTAL"],
                    header_color=0x50C878, title="VENTAS REALIZADAS",
                    show_total=True, total_label_span=2,
                    placeholder="NO HAY VENTAS REALIZADAS", rows=ventas_rows,
                )
            except Exception as exc:
                print(f"No se pudo usar la hoja pre-horneada, reconstruyendo en vivo: {exc}")
                prebaked = False

        if not prebaked:
            tabla_entrada = create_table(hoja, 1, 1, ["PRODUCTO", "PRECIO", "C."])
            tabla_entrada.header_color = 0x9B111E
            tabla_entrada.title = "INGRESE LOS DATOS"
            tabla_entrada.append(["", "", 1])

            cart = create_table(hoja, 1, 5, ["PRODUCTO", "PRECIO", "C.", "SUBTOTAL"])
            cart.header_color = 0x1CA9C9
            cart.title = "CARRITO DE COMPRA"
            cart.show_total = True
            cart.total_label_span = 2
            cart.placeholder = "EL CARRITO ESTÁ VACÍO"

            ventas = create_table(hoja, 6, 1, ["HORA", "PRODUCTO", "PRECIO", "C.", "SUBTOTAL"])
            ventas.header_color = 0x50C878
            ventas.title = "VENTAS REALIZADAS"
            ventas.show_total = True
            ventas.total_label_span = 2
            ventas.placeholder = "NO HAY VENTAS REALIZADAS"
            table_manager.load_sales(ventas)

        cart.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)
        ventas.limpiar_residuos_bajo_tabla(limpiar_total_izquierda=True)

    return tabla_entrada, cart, ventas
