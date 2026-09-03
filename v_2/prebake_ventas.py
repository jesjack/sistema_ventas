"""Pre-hornea share/main.ods con las 3 tablas (input, carrito, ventas) usando
odfpy, ANTES de que soffice abra el archivo.

Ejecutar con un Python normal (no el de LibreOffice, no necesita `uno`):
    python prebake_ventas.py

Si algo falla, no se guarda nada (share/main.ods queda intacto) y el script
sale con codigo distinto de cero. main.py detecta que el pre-horneado no
corrio (chequeo minimo de sanidad) y usa el camino lento de siempre.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from odf.opendocument import load
from odf.table import Table, TableRow, TableColumn, TableCell, CoveredTableCell
from odf.style import Style, TableCellProperties, TableColumnProperties, ParagraphProperties, TextProperties
from odf.number import CurrencyStyle, CurrencySymbol, Number, TimeStyle, Hours, Minutes, Seconds, Text as NumberText
from odf.text import P

from services.ventas_service import VentasService

MAIN_ODS = BASE_DIR / "share" / "main.ods"

# Mismos valores que table_modules/view.py, para que el resultado horneado
# se vea igual que el que hoy produce UNO en vivo.
EVEN_ROW_COLOR = "#f3f7ff"
ODD_ROW_COLOR = "#ffffff"
PLACEHOLDER_BG = "#ffffff"
PLACEHOLDER_TEXT_COLOR = "#666666"
ITEM_TEXT_COLOR = "#000000"

TEXT, CURRENCY, INTEGER, TIME = "text", "currency", "integer", "time"

# Cada tupla: (encabezado, kind)
INPUT_COLS = [("PRODUCTO", TEXT), ("PRECIO", CURRENCY), ("C.", INTEGER)]
CART_COLS = [("PRODUCTO", TEXT), ("PRECIO", CURRENCY), ("C.", INTEGER), ("SUBTOTAL", CURRENCY)]
VENTAS_COLS = [("HORA", TIME), ("PRODUCTO", TEXT), ("PRECIO", CURRENCY), ("C.", INTEGER), ("SUBTOTAL", CURRENCY)]

# Filas extra en blanco a reconstruir mas alla de lo que ocupan las 3 tablas,
# para barrer residuos visuales de sesiones anteriores (ver uso en prebake()).
CLEANUP_PAD_ROWS = 15


class PrebakeError(RuntimeError):
    pass


def build_number_formats(doc):
    """Construye formatos de moneda/hora propios y deterministas, en vez de
    reutilizar los que ya haya en el archivo.

    Antes este script buscaba y reutilizaba el formato de moneda ya presente en
    el documento (el que UNO genera vía format_column_as_currency). Resulto
    fragil, y el intento de reemplazarlo con un formato propio que incluia la
    variante roja condicional para negativos (via style:map) tampoco se pudo
    verificar que LibreOffice lo interprete como se espera. En este negocio
    precios/subtotales/totales nunca son negativos, asi que no hace falta esa
    logica condicional: un solo formato de moneda simple, siempre igual, sin
    mecanismo condicional que pueda fallar en silencio.
    """
    moneda = CurrencyStyle(name="pbCurrencyMXN", language="es", country="MX")
    moneda.addElement(CurrencySymbol(language="es", country="MX", text="$"))
    moneda.addElement(Number(decimalplaces=2, minintegerdigits=1, grouping="true"))
    doc.automaticstyles.addElement(moneda)

    hora = TimeStyle(name="pbTimeHHMMSS", language="es", country="MX")
    hora.addElement(Hours(style="long"))
    hora.addElement(NumberText(text=":"))
    hora.addElement(Minutes(style="long"))
    hora.addElement(NumberText(text=":"))
    hora.addElement(Seconds(style="long"))
    doc.automaticstyles.addElement(hora)

    return {CURRENCY: "pbCurrencyMXN", INTEGER: "N0", TIME: "pbTimeHHMMSS", TEXT: None}


# Columna (0-based, igual que en main.py) -> tipo de dato. Mismas columnas que
# antes recibian format_column_as_currency(2)/(4)/(8)/(10) y
# format_column_as_time(6) via UNO en cada arranque.
COLUMN_DEFAULT_KIND = {2: CURRENCY, 3: INTEGER, 4: CURRENCY, 6: TIME, 8: CURRENCY, 9: INTEGER, 10: CURRENCY}


def apply_column_default_formats(doc, table, number_formats):
    """Asigna el formato de numero por defecto a nivel de COLUMNA (no solo a
    las celdas que este script escribe), para que una fila agregada despues en
    vivo (por ejemplo un item real del carrito) tambien salga formateada como
    moneda/hora aunque este script nunca haya tocado esa celda en particular.
    Antes esto lo hacia main.py en cada arranque con format_column_as_currency/
    format_column_as_time via UNO; ahora se hornea una sola vez aqui.
    """
    defaults = {}
    for kind in (CURRENCY, INTEGER, TIME):
        nombre = f"pbColDefault{kind.title()}"
        estilo = Style(name=nombre, family="table-cell", parentstylename="Default",
                        datastylename=number_formats[kind])
        doc.automaticstyles.addElement(estilo)
        defaults[kind] = nombre

    columnas = table.getElementsByType(TableColumn)
    col_idx = 0
    for columna in columnas:
        rep_attr = columna.getAttribute("numbercolumnsrepeated")
        rep = int(rep_attr) if rep_attr else 1
        if rep == 1 and col_idx in COLUMN_DEFAULT_KIND:
            columna.setAttribute("defaultcellstylename", defaults[COLUMN_DEFAULT_KIND[col_idx]])
        col_idx += rep
        if col_idx > max(COLUMN_DEFAULT_KIND):
            break


# Anchos originales (en 1/100 mm, igual que sheet_admin.set_column_width via
# UNO) para las 12 columnas que usan las 3 tablas. Se convierten a cm para
# ODF (dividir entre 1000).
COLUMN_WIDTHS_1_100MM = [600, 7700, 1600, 600, 2300, 600, 1600, 7700, 1600, 600, 2300, 600]


def verify_and_restore_column_widths(doc, table):
    """Fuerza el ancho correcto en las 12 columnas usadas por las tablas, sin
    importar lo que tuvieran antes -- los anchos de columna resultaron
    susceptibles a descuadrarse (por ejemplo si alguien redimensiona una
    columna a mano en Calc y guarda). Aplicar el valor correcto siempre,
    en vez de solo "si hace falta", es lo que garantiza que quede bien:
    no hay forma de que quede mal sin que el proximo pre-horneado lo repare.
    Imprime un aviso cuando el ancho encontrado no coincidia, para que quede
    registro de que hubo que corregirlo.
    """
    estilos_por_ancho = {}
    columnas = table.getElementsByType(TableColumn)
    col_idx = 0
    for columna in columnas:
        rep_attr = columna.getAttribute("numbercolumnsrepeated")
        rep = int(rep_attr) if rep_attr else 1

        if rep == 1 and col_idx < len(COLUMN_WIDTHS_1_100MM):
            ancho_correcto_cm = COLUMN_WIDTHS_1_100MM[col_idx] / 1000
            ancho_texto = f"{ancho_correcto_cm:g}cm"

            ancho_actual = _leer_ancho_columna(doc, columna)
            if ancho_actual != ancho_texto:
                print(f"Columna {col_idx}: ancho era '{ancho_actual}', se restaura a '{ancho_texto}'.")

            if ancho_texto not in estilos_por_ancho:
                nombre = f"pbColWidth{col_idx}"
                estilo = Style(name=nombre, family="table-column")
                estilo.addElement(TableColumnProperties(columnwidth=ancho_texto))
                doc.automaticstyles.addElement(estilo)
                estilos_por_ancho[ancho_texto] = nombre

            columna.setAttribute("stylename", estilos_por_ancho[ancho_texto])

        col_idx += rep
        if col_idx >= len(COLUMN_WIDTHS_1_100MM):
            break


def _leer_ancho_columna(doc, columna):
    """Ancho actual de una columna (p.ej. '1.6cm'), o None si no se pudo leer."""
    nombre_estilo = None
    try:
        nombre_estilo = columna.getAttribute("stylename")
    except Exception:
        return None
    if not nombre_estilo:
        return None

    for estilo in doc.getElementsByType(Style):
        try:
            if estilo.getAttribute("name") != nombre_estilo:
                continue
            if estilo.getAttribute("family") != "table-column":
                continue
        except Exception:
            continue
        for props in estilo.getElementsByType(TableColumnProperties):
            try:
                return props.getAttribute("columnwidth")
            except Exception:
                return None
    return None


def _new_style(doc, name, background, bold, align_source, text_align=None,
               data_style_name=None, italic=False, text_color=None):
    kwargs = dict(name=name, family="table-cell", parentstylename="Default")
    if data_style_name:
        kwargs["datastylename"] = data_style_name
    style = Style(**kwargs)

    cell_props = dict(backgroundcolor=background, textalignsource=align_source, repeatcontent="false")
    style.addElement(TableCellProperties(**cell_props))

    if text_align:
        style.addElement(ParagraphProperties(textalign=text_align))

    text_kwargs = dict(fontweight=("bold" if bold else "normal"))
    if italic:
        text_kwargs["fontstyle"] = "italic"
    if text_color:
        text_kwargs["color"] = text_color
    else:
        text_kwargs["usewindowfontcolor"] = "true"
    style.addElement(TextProperties(**text_kwargs))

    doc.automaticstyles.addElement(style)
    return name


def build_role_styles(doc, table_prefix, header_color, number_formats):
    """Registra en doc.automaticstyles los estilos necesarios para una tabla y
    devuelve un dict {rol: {kind: nombre_de_estilo}}.
    """
    styles = {"header": {}, "item_even": {}, "item_odd": {}, "total_label": {}, "total_value": {}, "placeholder": {}}

    for kind in (TEXT, CURRENCY, INTEGER, TIME):
        data_style = number_formats.get(kind)

        styles["header"][kind] = _new_style(
            doc, f"pb{table_prefix}Header{kind.title()}",
            background=header_color, bold=True, align_source="fix", text_align="center",
            data_style_name=data_style,
        )
        styles["item_even"][kind] = _new_style(
            doc, f"pb{table_prefix}ItemEven{kind.title()}",
            background=EVEN_ROW_COLOR, bold=False, align_source="value-type",
            data_style_name=data_style, text_color=ITEM_TEXT_COLOR,
        )
        styles["item_odd"][kind] = _new_style(
            doc, f"pb{table_prefix}ItemOdd{kind.title()}",
            background=ODD_ROW_COLOR, bold=False, align_source="value-type",
            data_style_name=data_style, text_color=ITEM_TEXT_COLOR,
        )
        styles["total_label"][kind] = _new_style(
            doc, f"pb{table_prefix}TotalLabel{kind.title()}",
            background=header_color, bold=True, align_source="fix", text_align="end",
            data_style_name=data_style,
        )
        # El placeholder ("EL CARRITO ESTA VACIO"/"NO HAY VENTAS REALIZADAS")
        # muestra solo texto, pero se le asigna igual el data-style-name que
        # tendria un item real de esa columna: cuando una venta real llega en
        # vivo y reemplaza esta celda, el codigo en vivo solo cambia color/
        # peso de texto (nunca el formato numerico), asi que la celda debe
        # traer ya el formato correcto desde que se hornea, aunque hoy solo
        # se vea como texto centrado en italica.
        styles["placeholder"][kind] = _new_style(
            doc, f"pb{table_prefix}Placeholder{kind.title()}",
            background=PLACEHOLDER_BG, bold=False, align_source="fix", text_align="center",
            data_style_name=data_style, italic=True, text_color=PLACEHOLDER_TEXT_COLOR,
        )

    styles["total_value"][CURRENCY] = _new_style(
        doc, f"pb{table_prefix}TotalValue",
        background=header_color, bold=True, align_source="value-type",
        data_style_name=number_formats[CURRENCY],
    )

    return styles


def _value_cell(style_name, kind, value):
    if isinstance(value, bool):
        cell = TableCell(stylename=style_name, valuetype="boolean", booleanvalue="true" if value else "false")
        cell.addElement(P(text="VERDADERO" if value else "FALSO"))
        return cell

    if isinstance(value, (int, float)):
        cell = TableCell(stylename=style_name, valuetype="float", value=float(value))
        cell.addElement(P(text=str(value)))
        return cell

    texto = "" if value is None else str(value)
    cell = TableCell(stylename=style_name, valuetype="string") if texto else TableCell(stylename=style_name)
    if texto:
        cell.addElement(P(text=texto))
    return cell


def build_table_region(x, base_y, columnas, title, header_color, placeholder,
                        show_total, total_label_span, rows, styles):
    """Reproduce lo que create_table()+render() dejarian en la hoja, para una
    tabla dada. Devuelve {fila_y: {columna_offset (0-based dentro de la tabla): elemento}}.
    """
    region = {}
    n_cols = len(columnas)
    kinds = [kind for _nombre, kind in columnas]
    tiene_titulo = bool(title)
    header_y = base_y + (1 if tiene_titulo else 0)
    data_start_y = header_y + 1

    if tiene_titulo:
        fila = {}
        leading_kind = kinds[0]
        leading = TableCell(
            stylename=styles["header"][leading_kind], valuetype="string",
            numbercolumnsspanned=n_cols, numberrowsspanned=1,
        )
        leading.addElement(P(text=title))
        fila[0] = leading
        for i in range(1, n_cols):
            fila[i] = CoveredTableCell(stylename=styles["header"][kinds[i]])
        region[base_y] = fila

    fila = {}
    for i, (nombre, kind) in enumerate(columnas):
        celda = TableCell(stylename=styles["header"][kind], valuetype="string")
        celda.addElement(P(text=nombre))
        fila[i] = celda
    region[header_y] = fila

    cantidad_items = len(rows)
    muestra_placeholder = bool(placeholder is not None and cantidad_items == 0)

    if muestra_placeholder:
        fila = {}
        leading = TableCell(
            stylename=styles["placeholder"][kinds[0]], valuetype="string",
            numbercolumnsspanned=n_cols, numberrowsspanned=1,
        )
        leading.addElement(P(text=placeholder))
        fila[0] = leading
        for i in range(1, n_cols):
            fila[i] = CoveredTableCell(stylename=styles["placeholder"][kinds[i]])
        region[data_start_y] = fila
    else:
        for offset, row_values in enumerate(rows):
            fila_y = data_start_y + offset
            banda = "item_even" if offset % 2 == 0 else "item_odd"
            fila = {}
            for i, kind in enumerate(kinds):
                fila[i] = _value_cell(styles[banda][kind], kind, row_values[i])
            region[fila_y] = fila

    if show_total:
        total_row_y = data_start_y + (1 if muestra_placeholder else cantidad_items)
        total = 0.0
        if not muestra_placeholder:
            for row_values in rows:
                try:
                    total += float(row_values[-1])
                except (TypeError, ValueError):
                    continue

        penultimate_idx = n_cols - 2 if n_cols >= 2 else n_cols - 1
        start_total_idx = penultimate_idx - total_label_span + 1
        if start_total_idx < 0:
            raise PrebakeError("total_label_span se sale del rango de la tabla")

        fila = region.setdefault(total_row_y, {})
        label_kind = kinds[start_total_idx]
        leading = TableCell(
            stylename=styles["total_label"][label_kind], valuetype="string",
            numbercolumnsspanned=total_label_span, numberrowsspanned=1,
        )
        leading.addElement(P(text="TOTAL"))
        fila[start_total_idx] = leading
        for i in range(start_total_idx + 1, penultimate_idx + 1):
            fila[i] = CoveredTableCell(stylename=styles["total_label"][kinds[i]])

        fila[n_cols - 1] = _value_cell(styles["total_value"][CURRENCY], CURRENCY, total)

    return x, region


def _blank_cell():
    return TableCell()


def _gap_cell_col0():
    return TableCell(stylename="Default")


def _gap_cell_col5():
    return TableCell(stylename="Default")


def _tail_cells():
    """Reproduce exactamente la cola que ya existe hoy en cada fila usada:
    columna 11 en blanco, columnas 12-15 con estilo Default (repetidas 4 veces),
    y el resto de la hoja (16368 columnas) con el estilo protegido ce1.
    Vista una vez en el archivo real (main.ods) via inspeccion directa.
    """
    col11 = TableCell()
    col12_15 = TableCell(stylename="Default", numbercolumnsrepeated=4)
    resto = TableCell(stylename="ce1", numbercolumnsrepeated=16368)
    return [col11, col12_15, resto]


def build_full_row(row_index, contribuciones):
    """contribuciones: lista de (x_base, n_cols, region) de cada tabla.
    Arma la fila completa: gap columna 0, contenido de cada tabla en su rango,
    gap columna 5 (separador), y la cola fija despues de la columna 10.
    """
    row = TableRow(stylename="ro1")
    row.addElement(_gap_cell_col0())

    # columnas 1-4 (input/cart) y columna 5 (gap) y columnas 6-10 (ventas)
    columnas_por_indice = {}
    for x_base, n_cols, region in contribuciones:
        fila = region.get(row_index)
        if not fila:
            continue
        for offset, celda in fila.items():
            columnas_por_indice[x_base + offset] = celda

    for col in range(1, 11):
        if col == 5:
            row.addElement(_gap_cell_col5())
            continue
        celda = columnas_por_indice.get(col)
        row.addElement(celda if celda is not None else _blank_cell())

    for celda in _tail_cells():
        row.addElement(celda)

    return row


def _table_rows(table):
    """Filas reales del elemento table:table, leidas directo de childNodes.

    A proposito no se usa table.getElementsByType(TableRow): ese metodo cachea
    la lista la primera vez que se llama, y la cache no se actualiza cuando se
    insertan/eliminan filas despues (insertBefore/removeChild no la tocan) --
    usarlo aqui devolveria listas desactualizadas a media reconstruccion.
    """
    return [hijo for hijo in table.childNodes if hijo.qname[1] == "table-row"]


def _remove_child_safe(parent, child):
    """Como table.removeChild(), pero tolera que odfpy no haya cacheado el
    elemento: la eliminacion real de childNodes ya ocurrio antes de que esa
    actualizacion de cache falle, asi que el documento queda correcto igual.
    """
    try:
        parent.removeChild(child)
    except Exception:
        pass


def rebuild_rows(table, needed_count, contribuciones):
    """Borra TODAS las filas existentes de la tabla y escribe unicamente las
    `needed_count` que hacen falta -- nada de bloques table:number-rows-
    repeated de relleno al final. ODF no exige declarar la grilla completa de
    Calc (~1M filas): un table:table con solo las filas necesarias es valido
    y Calc lo abre igual (confirmado a mano). Version anterior intentaba
    partir con cuidado el bloque repetido grande que ya traia el archivo --
    ahi vivia un bug que trunco la hoja una vez; esta version es mas simple y
    ese codigo ya no existe.
    """
    for fila_vieja in _table_rows(table):
        _remove_child_safe(table, fila_vieja)

    for row_index in range(needed_count):
        table.addElement(build_full_row(row_index, contribuciones))


PB_STYLE_PREFIX = "pb"


def remove_previous_pb_styles(doc):
    """Elimina cualquier estilo con nombre que empiece con "pb" de una corrida
    anterior de este script, antes de crear los nuevos. Sin esto, correr el
    script mas de una vez sobre el mismo archivo deja dos definiciones con el
    mismo nombre (una vieja sin usar, una nueva) -- eso es exactamente lo que
    causo que LibreOffice perdiera la variante positiva del formato de moneda
    y todo se viera en rojo/negativo pese a que los valores eran positivos.
    """
    # rebuild_caches() puebla doc.element_dict; sin esto, removeChild() puede
    # fallar con un ValueError crudo al intentar actualizar un cache que nunca
    # se lleno para estos elementos.
    doc.rebuild_caches()

    for coleccion in (doc.automaticstyles, doc.styles):
        for hijo in list(coleccion.childNodes):
            nombre = None
            try:
                nombre = hijo.getAttribute("name")
            except Exception:
                continue
            if nombre and nombre.startswith(PB_STYLE_PREFIX):
                try:
                    coleccion.removeChild(hijo)
                except Exception:
                    pass

    # Bug real que causo que varios estilos "desaparecieran": remove_from_caches
    # puede fallar a medias arriba (capturado por el except) y dejar el nombre
    # del estilo viejo colgado en doc._styles_dict aunque el elemento ya se
    # elimino del arbol. Cuando mas adelante se crea un estilo NUEVO con ese
    # mismo nombre, odfpy lo interpreta como colision y le cambia el nombre en
    # silencio (le antepone "M") -- la celda que lo referencia se queda
    # apuntando al nombre original, que ya no existe. Limpiar y reconstruir el
    # cache aqui, reflejando el arbol YA SIN los estilos viejos, evita esa
    # colision fantasma.
    doc.clear_caches()
    doc.rebuild_caches()


def prebake():
    if not MAIN_ODS.exists():
        raise PrebakeError(f"No se encontro {MAIN_ODS}")

    doc = load(str(MAIN_ODS))
    table = doc.spreadsheet.getElementsByType(Table)[0]

    remove_previous_pb_styles(doc)
    verify_and_restore_column_widths(doc, table)

    number_formats = build_number_formats(doc)
    apply_column_default_formats(doc, table, number_formats)

    ventas_service = VentasService()
    ventas_rows = ventas_service.obtener_ventas()

    input_styles = build_role_styles(doc, "Input", "#9b111e", number_formats)
    cart_styles = build_role_styles(doc, "Cart", "#1ca9c9", number_formats)
    ventas_styles = build_role_styles(doc, "Ventas", "#50c878", number_formats)

    input_x, input_region = build_table_region(
        x=1, base_y=1, columnas=INPUT_COLS, title="INGRESE LOS DATOS",
        header_color="#9b111e", placeholder=None, show_total=False,
        total_label_span=1, rows=[("", "", 1)], styles=input_styles,
    )

    cart_x, cart_region = build_table_region(
        x=1, base_y=5, columnas=CART_COLS, title="CARRITO DE COMPRA",
        header_color="#1ca9c9", placeholder="EL CARRITO ESTÁ VACÍO",
        show_total=True, total_label_span=2, rows=[], styles=cart_styles,
    )

    ventas_x, ventas_region = build_table_region(
        x=6, base_y=1, columnas=VENTAS_COLS, title="VENTAS REALIZADAS",
        header_color="#50c878", placeholder="NO HAY VENTAS REALIZADAS",
        show_total=True, total_label_span=2, rows=ventas_rows, styles=ventas_styles,
    )

    contribuciones = [
        (input_x, len(INPUT_COLS), input_region),
        (cart_x, len(CART_COLS), cart_region),
        (ventas_x, len(VENTAS_COLS), ventas_region),
    ]

    max_row_input = max(input_region.keys())
    max_row_cart = max(cart_region.keys())
    max_row_ventas = max(ventas_region.keys())
    needed_count = max(max_row_input, max_row_cart, max_row_ventas) + 1

    # Se reconstruyen algunas filas extra en blanco mas alla de lo que
    # realmente ocupan las 3 tablas, para barrer cualquier residuo visual de
    # sesiones anteriores (por ejemplo si ayer hubo mas ventas que hoy y
    # quedaron filas con estilo/color de una tabla mas grande).
    rebuild_rows(table, needed_count + CLEANUP_PAD_ROWS, contribuciones)

    doc.save(str(MAIN_ODS))


if __name__ == "__main__":
    # Argumento opcional: ruta a un .ods de prueba, para hornear ahi en vez
    # de share/main.ods mientras se valida un cambio visualmente.
    #   python prebake_ventas.py share/main_test.ods
    if len(sys.argv) > 1:
        MAIN_ODS = Path(sys.argv[1])

    try:
        prebake()
    except Exception as exc:  # noqa: BLE001 - respaldo intencional: nunca dejar el .ods a medias
        print(f"Pre-horneado fallido, {MAIN_ODS.name} no se modifico: {exc}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Pre-horneado completado ({MAIN_ODS}).")
