class Table(list):
    def __init__(self, hoja, x, y, columnas, rango):
        super().__init__()
        self.hoja = hoja
        self.x = x
        self.y = y
        self.columnas = tuple(columnas)
        self.rango = rango
        self.base_y = y
        self.titulo = ""
        self.titulo_rango = None
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

    def _aplicar_color_fila(self, fila_y, color):
        fin_columna = self.x + len(self.columnas) - 1
        rango_fila = self.hoja.getCellRangeByPosition(self.x, fila_y, fin_columna, fila_y)
        if color is None:
            rango_fila.CellBackColor = -1
        else:
            rango_fila.CellBackColor = int(color)

    def _aplicar_color_celda(self, celda, color):
        if color is None:
            celda.CellBackColor = -1
        else:
            celda.CellBackColor = int(color)

    def _aplicar_estilo_encabezado(self, celda):
        celda.CharWeight = 150.0
        celda.HoriJustify = 2

    def _aplicar_estilo_total(self, celda, alineacion):
        celda.CharWeight = 150.0
        celda.HoriJustify = alineacion

    def _aplicar_estilo_placeholder(self, celda):
        import uno

        celda.CharWeight = 100.0
        celda.CharColor = 0x666666
        celda.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "ITALIC")
        celda.HoriJustify = 2

    def _aplicar_color_encabezado(self, encabezados_y):
        color = self._header_color
        fin_columna = self.x + len(self.columnas) - 1

        if self.titulo_rango is not None:
            if color is None:
                self.titulo_rango.CellBackColor = -1
            else:
                self.titulo_rango.CellBackColor = int(color)

        for indice in range(len(self.columnas)):
            celda = self.hoja.getCellByPosition(self.x + indice, encabezados_y)
            self._aplicar_color_celda(celda, color)
            self._aplicar_estilo_encabezado(celda)

        if self.titulo_rango is not None:
            self._aplicar_estilo_encabezado(self.hoja.getCellByPosition(self.x, self.base_y))
            self.rango = self.hoja.getCellRangeByPosition(self.x, self.base_y, fin_columna, self.data_start_y + len(self) - 1 if self else encabezados_y)

    def _limpiar_render_anterior(self):
        if self._rendered_rows < 1:
            return

        fin_columna = self.x + len(self.columnas) - 1
        fin_fila = self.base_y + self._rendered_rows - 1

        if self._rendered_show_total:
            self._descombinar_total_label(self.base_y + self._rendered_rows - 1, self._rendered_total_label_span)

        if self._rendered_placeholder:
            self._descombinar_placeholder(self._rendered_has_title)

        rango = self.hoja.getCellRangeByPosition(self.x, self.base_y, fin_columna, fin_fila)
        rango.clearContents(31)
        rango.CellBackColor = -1

    def _descombinar_total_label(self, total_row_y, span):
        if span <= 1:
            return

        fin_columna = self.x + len(self.columnas) - 2
        inicio_columna = fin_columna - span + 1
        rango = self.hoja.getCellRangeByPosition(inicio_columna, total_row_y, fin_columna, total_row_y)
        rango.merge(False)

    def _descombinar_placeholder(self, had_title):
        fila_placeholder = self.base_y + (2 if had_title else 1)
        fin_columna = self.x + len(self.columnas) - 1
        rango = self.hoja.getCellRangeByPosition(self.x, fila_placeholder, fin_columna, fila_placeholder)
        rango.merge(False)

    def _render(self):
        fin_columna = self.x + len(self.columnas) - 1
        tiene_titulo = bool(self.titulo)
        tiene_items = len(self) > 0
        muestra_placeholder = bool(self._placeholder is not None and not tiene_items)
        muestra_total = bool(self._show_total)

        self._limpiar_render_anterior()

        if tiene_titulo:
            self.titulo_rango = self.hoja.getCellRangeByPosition(self.x, self.base_y, fin_columna, self.base_y)
            self.titulo_rango.merge(True)

            self.hoja.getCellByPosition(self.x, self.base_y).String = self.titulo
            encabezados_y = self.base_y + 1
            self.y = encabezados_y
        else:
            encabezados_y = self.base_y
            self.y = encabezados_y

        for indice, nombre in enumerate(self.columnas):
            celda = self.hoja.getCellByPosition(self.x + indice, encabezados_y)
            celda.String = str(nombre)

        self._aplicar_color_encabezado(encabezados_y)

        if muestra_placeholder:
            fila_placeholder = self.data_start_y
            rango_placeholder = self.hoja.getCellRangeByPosition(self.x, fila_placeholder, fin_columna, fila_placeholder)
            rango_placeholder.merge(True)
            celda_placeholder = self.hoja.getCellByPosition(self.x, fila_placeholder)
            celda_placeholder.String = self._placeholder
            self._aplicar_estilo_placeholder(celda_placeholder)
            self._aplicar_color_celda(rango_placeholder, self._odd_row_color)
        else:
            for fila_offset, item in enumerate(self):
                fila_y = self.data_start_y + fila_offset
                self._escribir_fila(fila_y, item)
                color_fila = self._even_row_color if fila_offset % 2 == 0 else self._odd_row_color
                self._aplicar_color_fila(fila_y, color_fila)

        # Render total row if enabled
        total_row_y = self.data_start_y + (1 if muestra_placeholder else len(self))
        if muestra_total:
            # compute sum of last column for numeric values
            total = 0.0
            for item in self:
                try:
                    val = float(item[-1])
                except Exception:
                    continue
                total += val

            penultimate_idx = self.x + len(self.columnas) - 2 if len(self.columnas) >= 2 else fin_columna
            last_idx = fin_columna
            start_total_idx = penultimate_idx - self._total_label_span + 1

            if start_total_idx < self.x:
                raise ValueError("total_label_span se sale del rango de la tabla")

            self._descombinar_total_label(total_row_y, self._total_label_span)

            cel_total_range = self.hoja.getCellRangeByPosition(start_total_idx, total_row_y, penultimate_idx, total_row_y)
            cel_total_range.merge(True)
            cel_total_label = self.hoja.getCellByPosition(start_total_idx, total_row_y)
            cel_total_value = self.hoja.getCellByPosition(last_idx, total_row_y)
            cel_total_label.String = "TOTAL"
            # format total: integer if whole
            cel_total_value.Value = float(total)

            # apply header color to both cells
            self._aplicar_color_celda(cel_total_range, self._header_color)
            self._aplicar_color_celda(cel_total_value, self._header_color)
            self._aplicar_estilo_total(cel_total_range, 3)
            self._aplicar_estilo_total(cel_total_value, 0)

        inicio = self.base_y if tiene_titulo else encabezados_y
        fin_fila = self.data_start_y + len(self) - 1 if self else encabezados_y
        if muestra_placeholder:
            fin_fila = self.data_start_y
        if muestra_total:
            fin_fila = fin_fila + 1
        self.rango = self.hoja.getCellRangeByPosition(self.x, inicio, fin_columna, fin_fila)
        self._rendered_rows = (2 if tiene_titulo else 1) + (1 if muestra_placeholder else len(self)) + (1 if muestra_total else 0)
        self._rendered_has_title = tiene_titulo
        self._rendered_show_total = muestra_total
        self._rendered_placeholder = muestra_placeholder
        self._rendered_total_label_span = self._total_label_span

    @property
    def title(self):
        return self.titulo

    @title.setter
    def title(self, value):
        if value is None:
            if self.titulo_rango is not None:
                self.titulo_rango.merge(False)
            self.titulo = ""
            self.titulo_rango = None
            self._render()
            return

        self.titulo = str(value)
        self._render()

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
        normalized = self._normalizar_item(item)
        super().append(normalized)
        self._render()

    def extend(self, items):
        normalized_items = [self._normalizar_item(item) for item in items]
        super().extend(normalized_items)
        self._render()

    def insert(self, index, item):
        normalized = self._normalizar_item(item)
        super().insert(index, normalized)
        self._render()

    def pop(self, index=-1):
        item = super().pop(index)
        self._render()
        return item

    def remove(self, item):
        normalized = self._normalizar_item(item)
        super().remove(normalized)
        self._render()

    def clear(self):
        super().clear()
        self._render()

    def __setitem__(self, index, value):
        if isinstance(index, slice):
            normalized = [self._normalizar_item(item) for item in value]
            super().__setitem__(index, normalized)
        else:
            super().__setitem__(index, self._normalizar_item(value))
        self._render()

    def __delitem__(self, index):
        super().__delitem__(index)
        self._render()

    def add_item(self, item):
        self.append(item)
        return self[-1]

    def remove_item(self, index=-1):
        return self.pop(index)


def create_table(hoja, x, y, columnas):
    """Crea una tabla vacía con encabezados en una hoja de Calc.

    x e y se interpretan como coordenadas de celda base 0.
    `columnas` debe ser una lista o tupla con los nombres de las columnas.
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