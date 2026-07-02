class TableViewRenderer:
    def __init__(self, table):
        self.table = table

    def _alineacion_default(self):
        import uno

        return uno.Enum("com.sun.star.table.CellHoriJustify", "STANDARD")

    def _resetear_formato_celda(self, celda):
        celda.CellBackColor = -1
        celda.CharColor = -1
        celda.CharWeight = 100.0
        celda.HoriJustify = self._alineacion_default()

        try:
            import uno

            celda.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "NONE")
        except Exception:
            pass

    def _limpiar_rango_fila(self, fila_y, inicio_columna, fin_columna):
        rango = self.table.hoja.getCellRangeByPosition(inicio_columna, fila_y, fin_columna, fila_y)

        try:
            rango.merge(False)
        except Exception:
            pass

        rango.clearContents(31)
        rango.CellBackColor = -1
        rango.CharColor = -1
        rango.HoriJustify = self._alineacion_default()

        try:
            import uno

            rango.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "NONE")
        except Exception:
            pass

        rango.CharWeight = 100.0

        for columna_idx in range(inicio_columna, fin_columna + 1):
            self._resetear_formato_celda(self.table.hoja.getCellByPosition(columna_idx, fila_y))

    def _fila_esta_limpia(self, fila_y, inicio_columna, fin_columna):
        # print(range(inicio_columna, fin_columna + 1))
        for columna_idx in range(inicio_columna, fin_columna + 1):
            celda = self.table.hoja.getCellByPosition(columna_idx, fila_y)
            texto = str(celda.String).strip()
            if texto:
                return False
            if float(celda.Value) != 0.0:
                return False
            if int(getattr(celda, "CellBackColor", -1)) != -1:
                return False
            if int(getattr(celda, "CharColor", -1)) != -1:
                return False

        return True

    def aplicar_color_fila(self, fila_y, color):
        fin_columna = self.table.x + len(self.table.columnas) - 1
        rango_fila = self.table.hoja.getCellRangeByPosition(self.table.x, fila_y, fin_columna, fila_y)
        if color is None:
            rango_fila.CellBackColor = -1
        else:
            rango_fila.CellBackColor = int(color)

    def limpiar_fila(self, fila_y):
        fin_columna = self.table.x + len(self.table.columnas) - 1
        rango = self.table.hoja.getCellRangeByPosition(self.table.x, fila_y, fin_columna, fila_y)
        rango.clearContents(31)
        rango.CellBackColor = -1
        rango.CharColor = -1
        rango.HoriJustify = self._alineacion_default()

        for columna_idx in range(self.table.x, fin_columna + 1):
            self._resetear_formato_celda(self.table.hoja.getCellByPosition(columna_idx, fila_y))

    def render_total_row(self, total_row_y):
        total = 0.0
        for item in self.table._iterar_items_locales():
            try:
                val = float(item[-1])
            except Exception:
                continue
            total += val

        penultimate_idx = self.table.x + len(self.table.columnas) - 2 if len(self.table.columnas) >= 2 else self.table.x + len(self.table.columnas) - 1
        last_idx = self.table.x + len(self.table.columnas) - 1
        start_total_idx = penultimate_idx - self.table._total_label_span + 1

        if start_total_idx < self.table.x:
            raise ValueError("total_label_span se sale del rango de la tabla")

        self.descombinar_total_label(total_row_y, self.table._total_label_span)

        cel_total_range = self.table.hoja.getCellRangeByPosition(start_total_idx, total_row_y, penultimate_idx, total_row_y)
        cel_total_range.merge(True)
        cel_total_label = self.table.hoja.getCellByPosition(start_total_idx, total_row_y)
        cel_total_value = self.table.hoja.getCellByPosition(last_idx, total_row_y)
        cel_total_label.String = "TOTAL"
        cel_total_value.Value = float(total)
        cel_total_range.CharColor = -1
        cel_total_value.CharColor = -1

        self.aplicar_color_celda(cel_total_range, self.table._header_color)
        self.aplicar_color_celda(cel_total_value, self.table._header_color)
        self.aplicar_estilo_total(cel_total_range, 3)
        self.aplicar_estilo_total(cel_total_value, 0)

    def aplicar_color_celda(self, celda, color):
        if color is None:
            celda.CellBackColor = -1
        else:
            celda.CellBackColor = int(color)

    def aplicar_estilo_encabezado(self, celda):
        celda.CharWeight = 150.0
        celda.HoriJustify = 2

    def aplicar_estilo_total(self, celda, alineacion):
        celda.CharWeight = 150.0
        celda.HoriJustify = alineacion

    def aplicar_estilo_placeholder(self, celda):
        import uno

        celda.CharWeight = 100.0
        celda.CharColor = 0x666666
        celda.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "ITALIC")
        celda.HoriJustify = 2

    def aplicar_estilo_item(self, celda):
        celda.CharWeight = 100.0
        celda.CharColor = 0x000000
        try:
            import uno

            celda.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "NONE")
        except Exception:
            pass

    def aplicar_estilo_fila_items(self, fila_y):
        fin_columna = self.table.x + len(self.table.columnas) - 1
        for columna_idx in range(self.table.x, fin_columna + 1):
            celda = self.table.hoja.getCellByPosition(columna_idx, fila_y)
            self.aplicar_estilo_item(celda)

    def aplicar_color_encabezado(self, encabezados_y):
        color = self.table._header_color
        fin_columna = self.table.x + len(self.table.columnas) - 1

        if self.table.titulo_rango is not None:
            if color is None:
                self.table.titulo_rango.CellBackColor = -1
            else:
                self.table.titulo_rango.CellBackColor = int(color)

        for indice in range(len(self.table.columnas)):
            celda = self.table.hoja.getCellByPosition(self.table.x + indice, encabezados_y)
            self.aplicar_color_celda(celda, color)
            self.aplicar_estilo_encabezado(celda)
            celda.CharColor = -1

        if self.table.titulo_rango is not None:
            self.aplicar_estilo_encabezado(self.table.hoja.getCellByPosition(self.table.x, self.table.base_y))
            cantidad_items = self.table._obtener_cantidad_items()
            fin_fila = self.table.data_start_y + cantidad_items - 1 if cantidad_items > 0 else encabezados_y
            self.table.rango = self.table.hoja.getCellRangeByPosition(self.table.x, self.table.base_y, fin_columna, fin_fila)

    def limpiar_render_anterior(self):
        if self.table._rendered_rows < 1:
            return

        fin_columna = self.table.x + len(self.table.columnas) - 1
        fin_fila = self.table.base_y + self.table._rendered_rows - 1

        if self.table._rendered_show_total:
            self.descombinar_total_label(self.table.base_y + self.table._rendered_rows - 1, self.table._rendered_total_label_span)

        if self.table._rendered_placeholder:
            self.descombinar_placeholder(self.table._rendered_has_title)

        rango = self.table.hoja.getCellRangeByPosition(self.table.x, self.table.base_y, fin_columna, fin_fila)
        rango.clearContents(31)
        rango.CellBackColor = -1
        rango.CharColor = -1

    def limpiar_render_anterior_completo(self):
        if self.table._rendered_rows < 1:
            return

        fin_columna = self.table.x + len(self.table.columnas) - 1
        fin_fila = self.table.base_y + self.table._rendered_rows - 1

        if self.table._rendered_show_total:
            self.descombinar_total_label(self.table.base_y + self.table._rendered_rows - 1, self.table._rendered_total_label_span)

        if self.table._rendered_placeholder:
            self.descombinar_placeholder(self.table._rendered_has_title)

        for fila_y in range(self.table.base_y, fin_fila + 1):
            self._limpiar_rango_fila(fila_y, self.table.x, fin_columna)

    def limpiar_residuos_bajo_encabezados(self):
        if self.table._rendered_rows < 1:
            return

        fin_columna = self.table.x + len(self.table.columnas) - 1
        inicio_fila = self.table.data_start_y
        fin_fila = self.table.base_y + self.table._rendered_rows - 1

        if self.table._rendered_show_total:
            self.descombinar_total_label(fin_fila, self.table._rendered_total_label_span)

        if self.table._rendered_placeholder:
            self.descombinar_placeholder(self.table._rendered_has_title)

        for fila_y in range(inicio_fila, fin_fila + 1):
            self._limpiar_rango_fila(fila_y, self.table.x, fin_columna)

    def limpiar_residuos_bajo_tabla(self, hasta_fila=None, limpiar_total_izquierda=True):
        inicio_fila = self.table.base_y + self.table._rendered_rows
        fin_columna = self.table.x + len(self.table.columnas) - 1

        if hasta_fila is None:
            fila_y = inicio_fila
            while True:
                if self._fila_esta_limpia(fila_y, self.table.x, fin_columna):
                    # print(f"Fila {fila_y} está limpia. Deteniendo limpieza de residuos.")
                    break
                print(f"Limpiando fila {fila_y} debajo de la tabla...")
                self._limpiar_rango_fila(fila_y, self.table.x, fin_columna)
                fila_y += 1
        else:
            if hasta_fila < inicio_fila:
                return

            for fila_y in range(inicio_fila, hasta_fila + 1):
                self._limpiar_rango_fila(fila_y, self.table.x, fin_columna)

        if not limpiar_total_izquierda or not self.table._show_total:
            return

        cantidad_items = self.table._obtener_cantidad_items()
        muestra_placeholder = bool(self.table._placeholder is not None and cantidad_items == 0)
        total_row_y = self.table._fila_total_y(cantidad_items, muestra_placeholder)

        penultimate_idx = self.table.x + len(self.table.columnas) - 2 if len(self.table.columnas) >= 2 else self.table.x + len(self.table.columnas) - 1
        start_total_idx = penultimate_idx - self.table._total_label_span + 1

        if start_total_idx > self.table.x:
            self._limpiar_rango_fila(total_row_y, self.table.x, start_total_idx - 1)

    def descombinar_total_label(self, total_row_y, span):
        if span <= 1:
            return

        fin_columna = self.table.x + len(self.table.columnas) - 2
        inicio_columna = fin_columna - span + 1
        rango = self.table.hoja.getCellRangeByPosition(inicio_columna, total_row_y, fin_columna, total_row_y)
        rango.merge(False)

    def descombinar_placeholder(self, had_title):
        fila_placeholder = self.table.base_y + (2 if had_title else 1)
        fin_columna = self.table.x + len(self.table.columnas) - 1
        rango = self.table.hoja.getCellRangeByPosition(self.table.x, fila_placeholder, fin_columna, fila_placeholder)
        rango.merge(False)

    def render(self, sync_from_sheet=True, limpiar_completamente=False):
        if sync_from_sheet:
            self.table._sincronizar_desde_hoja()

        fin_columna = self.table.x + len(self.table.columnas) - 1
        tiene_titulo = bool(self.table.title)
        cantidad_items = self.table._obtener_cantidad_items()
        tiene_items = cantidad_items > 0
        muestra_placeholder = bool(self.table._placeholder is not None and not tiene_items)
        muestra_total = bool(self.table._show_total)

        if limpiar_completamente:
            self.limpiar_render_anterior_completo()
        else:
            self.limpiar_render_anterior()

        if tiene_titulo:
            self.table.titulo_rango = self.table.hoja.getCellRangeByPosition(self.table.x, self.table.base_y, fin_columna, self.table.base_y)
            self.table.titulo_rango.merge(True)

            self.table.hoja.getCellByPosition(self.table.x, self.table.base_y).String = self.table.title
            encabezados_y = self.table.base_y + 1
            self.table.y = encabezados_y
        else:
            encabezados_y = self.table.base_y
            self.table.y = encabezados_y

        for indice, nombre in enumerate(self.table.columnas):
            celda = self.table.hoja.getCellByPosition(self.table.x + indice, encabezados_y)
            celda.String = str(nombre)

        self.aplicar_color_encabezado(encabezados_y)

        if muestra_placeholder:
            fila_placeholder = self.table.data_start_y
            rango_placeholder = self.table.hoja.getCellRangeByPosition(self.table.x, fila_placeholder, fin_columna, fila_placeholder)
            rango_placeholder.merge(True)
            celda_placeholder = self.table.hoja.getCellByPosition(self.table.x, fila_placeholder)
            celda_placeholder.String = self.table._placeholder
            self.aplicar_estilo_placeholder(celda_placeholder)
            self.aplicar_color_celda(rango_placeholder, self.table._odd_row_color)
        else:
            for fila_offset, item in enumerate(self.table._iterar_items_locales()):
                fila_y = self.table._fila_datos_y(fila_offset)
                self.table._escribir_fila(fila_y, item)
                color_fila = self.table._even_row_color if fila_offset % 2 == 0 else self.table._odd_row_color
                self.aplicar_color_fila(fila_y, color_fila)
                self.aplicar_estilo_fila_items(fila_y)

        total_row_y = self.table._fila_total_y(cantidad_items, muestra_placeholder)
        if muestra_total:
            self.render_total_row(total_row_y)

        inicio = self.table.base_y if tiene_titulo else encabezados_y
        fin_fila = self.table.data_start_y + cantidad_items - 1 if cantidad_items > 0 else encabezados_y
        if muestra_placeholder:
            fin_fila = self.table.data_start_y
        if muestra_total:
            fin_fila = fin_fila + 1
        self.table.rango = self.table.hoja.getCellRangeByPosition(self.table.x, inicio, fin_columna, fin_fila)
        self.table._rendered_rows = (2 if tiene_titulo else 1) + (1 if muestra_placeholder else cantidad_items) + (1 if muestra_total else 0)
        self.table._rendered_has_title = tiene_titulo
        self.table._rendered_show_total = muestra_total
        self.table._rendered_placeholder = muestra_placeholder
        self.table._rendered_total_label_span = self.table._total_label_span
