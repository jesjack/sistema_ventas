from .view import TableViewRenderer


class Table(list):
    def __init__(self, hoja, x, y, columnas, rango):
        super().__init__()
        self.hoja = hoja
        self.x = x
        self.y = y
        self.columnas = tuple(columnas)
        self.rango = rango
        self.base_y = y
        self._titulo = ""
        self._titulo_rango = None
        self._header_color = None
        self._even_row_color = 0xF3F7FF
        self._odd_row_color = 0xFFFFFF
        self._show_total = False
        self._total_label_span = 1
        self._placeholder = None
        self._rendered_rows = 1
        self._rendered_has_title = False
        self._rendered_show_total = False
        self._rendered_placeholder = False
        self._rendered_total_label_span = 1
        self._view = TableViewRenderer(self)

    @property
    def show_total(self):
        return bool(self._show_total)

    @show_total.setter
    def show_total(self, value):
        self._show_total = bool(value)
        self._render()

    @property
    def total_label_span(self):
        return self._total_label_span

    @total_label_span.setter
    def total_label_span(self, value):
        span = int(value)
        if span < 1:
            raise ValueError("total_label_span debe ser mayor que cero")
        if span > len(self.columnas) - 1:
            raise ValueError("total_label_span se sale del rango de la tabla")

        self._total_label_span = span
        self._render()

    @property
    def placeholder(self):
        return self._placeholder

    @placeholder.setter
    def placeholder(self, value):
        self._placeholder = None if value is None else str(value)
        self._render()

    @property
    def inicio(self):
        return (self.x, self.y)

    @property
    def fin(self):
        return (self.x + len(self.columnas) - 1, self.y)

    @property
    def data_start_y(self):
        return self.y + 1

    def _parsear_valor_celda(self, celda):
        texto = str(celda.String).strip()
        if not texto:
            return ""

        candidato = texto.replace(" ", "")
        if ":" in candidato:
            return texto

        if any(caracter.isalpha() for caracter in candidato):
            return texto

        if "," in candidato and "." in candidato:
            if candidato.rfind(",") > candidato.rfind("."):
                candidato = candidato.replace(".", "").replace(",", ".")
            else:
                candidato = candidato.replace(",", "")
        elif "," in candidato:
            candidato = candidato.replace(",", ".")

        try:
            numero = float(candidato)
        except ValueError:
            valor = celda.Value
            return int(valor) if float(valor).is_integer() else float(valor)

        if numero.is_integer():
            return int(numero)
        return numero

    def _leer_item_desde_hoja(self, indice):
        fila_y = self.data_start_y + indice
        return tuple(
            self._parsear_valor_celda(self.hoja.getCellByPosition(self.x + columna, fila_y))
            for columna in range(len(self.columnas))
        )

    def _sincronizar_desde_hoja(self):
        filas = [self._leer_item_desde_hoja(indice) for indice in range(super().__len__())]
        super().clear()
        super().extend(filas)

    def _normalizar_item(self, item):
        if isinstance(item, dict):
            return tuple(item.get(nombre, "") for nombre in self.columnas)

        if isinstance(item, (list, tuple)):
            if len(item) != len(self.columnas):
                raise ValueError("el item debe tener la misma cantidad de columnas")
            return tuple(item)

        raise TypeError("el item debe ser una lista, tupla o diccionario")

    def _escribir_fila(self, fila_y, item):
        for indice, valor in enumerate(item):
            celda = self.hoja.getCellByPosition(self.x + indice, fila_y)
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                celda.Value = float(valor)
            else:
                celda.String = str(valor)

    def _obtener_cantidad_items(self):
        return super().__len__()

    def _iterar_items_locales(self):
        return super().__iter__()

    def _fila_datos_y(self, indice):
        return self.data_start_y + indice

    def _fila_total_y(self, cantidad_items=None, muestra_placeholder=None):
        if cantidad_items is None:
            cantidad_items = self._obtener_cantidad_items()
        if muestra_placeholder is None:
            muestra_placeholder = bool(self._placeholder is not None and cantidad_items == 0)

        return self.data_start_y + (1 if muestra_placeholder else cantidad_items)

    def _descombinar_total_label(self, total_row_y, span):
        self._view.descombinar_total_label(total_row_y, span)

    def _descombinar_placeholder(self, had_title):
        self._view.descombinar_placeholder(had_title)

    def _limpiar_fila(self, fila_y):
        self._view.limpiar_fila(fila_y)

    def _aplicar_color_fila(self, fila_y, color):
        self._view.aplicar_color_fila(fila_y, color)

    def _aplicar_estilo_fila_items(self, fila_y):
        self._view.aplicar_estilo_fila_items(fila_y)

    def _render_total_row(self, total_row_y):
        self._view.render_total_row(total_row_y)

    def limpiar_residuos_bajo_tabla(self, hasta_fila=None, limpiar_total_izquierda=True):
        """Limpia restos de formato, combinaciones y contenido bajo la tabla.

        hasta_fila es la última fila que se quiere limpiar en la hoja.
        Si limpiar_total_izquierda es True, también limpia las celdas vacías a la
        izquierda del TOTAL en la fila de totales actual.
        """
        self._view.limpiar_residuos_bajo_tabla(
            hasta_fila,
            limpiar_total_izquierda=limpiar_total_izquierda,
        )

    def _render(self, sync_from_sheet=True, limpiar_completamente=False):
        self._view.render(
            sync_from_sheet=sync_from_sheet,
            limpiar_completamente=limpiar_completamente,
        )

    def __getitem__(self, index):
        self._sincronizar_desde_hoja()
        return super().__getitem__(index)

    def __iter__(self):
        self._sincronizar_desde_hoja()
        return super().__iter__()

    def __len__(self):
        self._sincronizar_desde_hoja()
        return super().__len__()

    def __bool__(self):
        self._sincronizar_desde_hoja()
        return super().__len__() > 0

    @property
    def title(self):
        return self._titulo

    @title.setter
    def title(self, value):
        if value is None:
            if self._titulo_rango is not None:
                self._titulo_rango.merge(False)
            self._titulo = ""
            self._titulo_rango = None
            self._render()
            return

        self._titulo = str(value)
        self._render()

    @property
    def titulo_rango(self):
        return self._titulo_rango

    @titulo_rango.setter
    def titulo_rango(self, value):
        self._titulo_rango = value

    @property
    def header_color(self):
        return self._header_color

    @header_color.setter
    def header_color(self, value):
        self._header_color = None if value is None else int(value)
        self._render()

    @property
    def even_row_color(self):
        return self._even_row_color

    @even_row_color.setter
    def even_row_color(self, value):
        self._even_row_color = None if value is None else int(value)
        self._render()

    @property
    def odd_row_color(self):
        return self._odd_row_color

    @odd_row_color.setter
    def odd_row_color(self, value):
        self._odd_row_color = None if value is None else int(value)
        self._render()

    def append(self, item):
        self._sincronizar_desde_hoja()
        normalized = self._normalizar_item(item)
        cantidad_items_antes = self._obtener_cantidad_items()
        tenia_placeholder = bool(self._placeholder is not None and cantidad_items_antes == 0)
        tenia_total = bool(self._show_total)
        total_row_y_antes = self._fila_total_y(cantidad_items_antes, tenia_placeholder)

        super().append(normalized)

        if tenia_placeholder:
            self._descombinar_placeholder(self._rendered_has_title)
            self._limpiar_fila(self.data_start_y)
        elif tenia_total:
            self._descombinar_total_label(total_row_y_antes, self._rendered_total_label_span)
            self._limpiar_fila(total_row_y_antes)

        fila_y = self._fila_datos_y(cantidad_items_antes)
        self._escribir_fila(fila_y, normalized)
        color_fila = self._even_row_color if cantidad_items_antes % 2 == 0 else self._odd_row_color
        self._aplicar_color_fila(fila_y, color_fila)
        self._aplicar_estilo_fila_items(fila_y)

        if tenia_total:
            self._render_total_row(self._fila_total_y())

        cantidad_items_despues = self._obtener_cantidad_items()
        self.rango = self.hoja.getCellRangeByPosition(
            self.x,
            self.base_y,
            self.x + len(self.columnas) - 1,
            self._fila_total_y(cantidad_items_despues, False) if tenia_total else self._fila_datos_y(cantidad_items_despues - 1),
        )
        self._rendered_rows = (2 if self._titulo else 1) + cantidad_items_despues + (1 if tenia_total else 0)
        self._rendered_has_title = bool(self._titulo)
        self._rendered_show_total = tenia_total
        self._rendered_placeholder = False
        self._rendered_total_label_span = self._total_label_span

    def extend(self, items):
        self._sincronizar_desde_hoja()
        normalized_items = [self._normalizar_item(item) for item in items]
        super().extend(normalized_items)
        self._render(sync_from_sheet=False)

    def insert(self, index, item):
        self._sincronizar_desde_hoja()
        normalized = self._normalizar_item(item)
        super().insert(index, normalized)
        self._render(sync_from_sheet=False)

    def pop(self, index=-1):
        self._sincronizar_desde_hoja()
        item = super().pop(index)
        self._render(sync_from_sheet=False)
        return item

    def remove(self, item):
        self._sincronizar_desde_hoja()
        normalized = self._normalizar_item(item)
        super().remove(normalized)
        self._render(sync_from_sheet=False)

    def clear(self):
        super().clear()
        fin_columna = self.x + len(self.columnas) - 1
        i = self.base_y + bool(self._titulo) + 1
        while True:
            if self._view._fila_esta_limpia(i, self.x, fin_columna):
                break
            self._view._limpiar_rango_fila(i, self.x, fin_columna)
            i += 1
        print("Carrito limpio.")
        self._render()

    def __setitem__(self, index, value):
        self._sincronizar_desde_hoja()
        if isinstance(index, slice):
            normalized = [self._normalizar_item(item) for item in value]
            super().__setitem__(index, normalized)
            self._render(sync_from_sheet=False)
            return

        normalized = self._normalizar_item(value)
        cantidad_items = self._obtener_cantidad_items()
        row_index = index if index >= 0 else cantidad_items + index

        super().__setitem__(index, normalized)

        if row_index < 0 or row_index >= cantidad_items:
            self._render(sync_from_sheet=False)
            return

        fila_y = self._fila_datos_y(row_index)
        self._escribir_fila(fila_y, normalized)
        color_fila = self._even_row_color if row_index % 2 == 0 else self._odd_row_color
        self._aplicar_color_fila(fila_y, color_fila)
        self._aplicar_estilo_fila_items(fila_y)

        if self._show_total:
            self._render_total_row(self._fila_total_y())

    def __delitem__(self, index):
        self._sincronizar_desde_hoja()
        super().__delitem__(index)
        self._render(sync_from_sheet=False)

    def add_item(self, item):
        self.append(item)
        return self[-1]

    def remove_item(self, index=-1):
        return self.pop(index)


def create_table(hoja, x, y, columnas):
    """Crea una tabla vacia con encabezados en una hoja de Calc.

    x e y se interpretan como coordenadas de celda base 0.
    columnas debe ser una lista o tupla con los nombres de las columnas.
    Devuelve una instancia de Table con los datos de la tabla creada.
    """
    if not isinstance(columnas, (list, tuple)):
        raise TypeError("columnas debe ser una lista o una tupla")
    if not columnas:
        raise ValueError("columnas no puede estar vacio")

    for indice, nombre in enumerate(columnas):
        celda = hoja.getCellByPosition(x + indice, y)
        celda.String = str(nombre)

    rango = hoja.getCellRangeByPosition(x, y, x + len(columnas) - 1, y)
    table = Table(hoja=hoja, x=x, y=y, columnas=tuple(columnas), rango=rango)
    table._rendered_rows = 1
    table._render()
    return table
