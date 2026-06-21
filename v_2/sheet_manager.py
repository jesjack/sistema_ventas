class SheetManager:
    def __init__(self, hoja, document=None):
        self.hoja = hoja
        self.document = document

    def _resolve_document(self, document=None):
        resolved_document = document or self.document
        if resolved_document is None:
            raise ValueError("se necesita un documento para obtener los formatos de moneda")
        return resolved_document

    def _get_currency_format_key(self, document=None, locale=None):
        import uno

        resolved_document = self._resolve_document(document)
        number_formats = resolved_document.getNumberFormats()
        if locale is None:
            resolved_locale = uno.createUnoStruct("com.sun.star.lang.Locale")
            resolved_locale.Language = "es"
            resolved_locale.Country = "MX"
            resolved_locale.Variant = ""
        else:
            resolved_locale = locale
        return number_formats.getStandardFormat(8, resolved_locale)

    def _apply_currency_format_to_range(self, cell_range, document=None, locale=None):
        cell_range.NumberFormat = self._get_currency_format_key(document=document, locale=locale)
        return cell_range.NumberFormat

    def set_column_width(self, index, width):
        if index < 0:
            raise ValueError("index debe ser mayor o igual que cero")
        if width <= 0:
            raise ValueError("width debe ser mayor que cero")

        columna = self.hoja.Columns.getByIndex(index)
        columna.Width = int(width)
        return columna.Width

    def set_row_height(self, index, height):
        if index < 0:
            raise ValueError("index debe ser mayor o igual que cero")
        if height <= 0:
            raise ValueError("height debe ser mayor que cero")

        fila = self.hoja.Rows.getByIndex(index)
        fila.Height = int(height)
        return fila.Height

    def format_column_as_currency(self, index, document=None, locale=None):
        if index < 0:
            raise ValueError("index debe ser mayor o igual que cero")

        max_row_index = 1048575
        columna = self.hoja.getCellRangeByPosition(index, 0, index, max_row_index)
        return self._apply_currency_format_to_range(columna, document=document, locale=locale)

    def format_row_as_currency(self, index, document=None, locale=None):
        if index < 0:
            raise ValueError("index debe ser mayor o igual que cero")

        max_column_index = 16383
        fila = self.hoja.getCellRangeByPosition(0, index, max_column_index, index)
        return self._apply_currency_format_to_range(fila, document=document, locale=locale)
    
    def add_row(self, input_table, cart_table):
        input_data = input_table.get_data()
        if not input_data:
            return
        
        new_row_index = cart_table.add_row(input_data)
        input_table.clear()
        cart_table.update_total()
        return new_row_index
