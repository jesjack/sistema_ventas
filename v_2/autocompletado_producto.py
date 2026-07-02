from __future__ import annotations

from datetime import datetime
from pathlib import Path

import unohelper
from com.sun.star.awt import Key as UnoKey  # pyright: ignore[reportMissingImports]
from com.sun.star.awt import XKeyHandler  # pyright: ignore[reportMissingImports]


LOG_PATH = Path(__file__).with_name("autocompletado_producto.log")


class AutocompletadoProductoHandler(unohelper.Base, XKeyHandler):
    def __init__(self, uno_context, documento, hoja, input_table, ventas_service, sheet_admin):
        self.uno_context = uno_context
        self.documento = documento
        self.hoja = hoja
        self.input_table = input_table
        self.ventas_service = ventas_service
        self.sheet_admin = sheet_admin
        self.selector_activo = False

    def _log(self, mensaje):
        texto = f"{datetime.now().isoformat(timespec='seconds')} {mensaje}"
        print(texto)
        try:
            with LOG_PATH.open("a", encoding="utf-8") as archivo:
                archivo.write(texto + "\n")
        except Exception:
            pass

    def _controlador(self):
        return self.documento.getCurrentController()

    def _seleccion_actual(self):
        try:
            return self.documento.getCurrentSelection()
        except Exception:
            try:
                return self._controlador().getCurrentSelection()
            except Exception:
                return None

    def _celda_b4_activa(self):
        try:
            controlador = self._controlador()
            hoja_activa = controlador.ActiveSheet
            if hoja_activa is None or hoja_activa.Name != self.hoja.Name:
                self._log("TAB ignorado: la hoja activa no coincide con la hoja de entrada.")
                return False

            seleccion = self._seleccion_actual()
            if seleccion is None:
                self._log("TAB ignorado: no se pudo obtener la seleccion actual.")
                return False

            if hasattr(seleccion, "supportsService") and seleccion.supportsService("com.sun.star.table.Cell"):
                direccion = seleccion.CellAddress
                es_b4 = int(direccion.Column) == 1 and int(direccion.Row) == 3
                if not es_b4:
                    self._log(
                        f"TAB ignorado: celda activa fuera de B4 (col={int(direccion.Column)} fila={int(direccion.Row)})."
                    )
                return es_b4

            if hasattr(seleccion, "supportsService") and seleccion.supportsService("com.sun.star.sheet.SheetCellRange"):
                direccion = seleccion.getRangeAddress()
                es_b4 = (
                    int(direccion.StartColumn) == 1
                    and int(direccion.EndColumn) == 1
                    and int(direccion.StartRow) == 3
                    and int(direccion.EndRow) == 3
                )
                if not es_b4:
                    self._log(
                        "TAB ignorado: la seleccion actual no corresponde a la celda B4 "
                        f"(sc={int(direccion.StartColumn)} ec={int(direccion.EndColumn)} sr={int(direccion.StartRow)} er={int(direccion.EndRow)})."
                    )
                return es_b4

            self._log(f"TAB ignorado: tipo de seleccion no soportado ({type(seleccion).__name__}).")
            return False
        except Exception as exc:
            self._log(f"TAB ignorado por error al validar B4: {exc}")
            return False

    def _aceptar_edicion_activa(self):
        try:
            dispatcher = self.uno_context.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.DispatchHelper", self.uno_context
            )
            frame = self._controlador().getFrame()
            dispatcher.executeDispatch(frame, ".uno:AcceptFormula", "", 0, tuple())
            self._log("Edicion activa aceptada antes de autocompletar.")
            return True
        except Exception as exc:
            self._log(f"No se pudo aceptar la edicion activa: {exc}")
            return False

    def _crear_dialogo_selector(self, coincidencias):
        smgr = self.uno_context.ServiceManager
        dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", self.uno_context)
        dialog_model.PositionX = 120
        dialog_model.PositionY = 80
        dialog_model.Width = 260
        dialog_model.Height = 180
        dialog_model.Title = "Seleccionar producto"

        lbl = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        lbl.Name = "lblInstruccion"
        lbl.PositionX = 8
        lbl.PositionY = 8
        lbl.Width = 244
        lbl.Height = 12
        lbl.Label = "Seleccione un producto del catalogo."
        dialog_model.insertByName("lblInstruccion", lbl)

        list_model = dialog_model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
        list_model.Name = "lstProductos"
        list_model.PositionX = 8
        list_model.PositionY = 24
        list_model.Width = 244
        list_model.Height = 112
        list_model.Dropdown = False
        list_model.StringItemList = tuple(nombre for _id, nombre in coincidencias)
        dialog_model.insertByName("lstProductos", list_model)

        btn_ok = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_ok.Name = "btnAceptar"
        btn_ok.PositionX = 140
        btn_ok.PositionY = 148
        btn_ok.Width = 46
        btn_ok.Height = 14
        btn_ok.Label = "Aceptar"
        btn_ok.PushButtonType = 1
        btn_ok.DefaultButton = True
        dialog_model.insertByName("btnAceptar", btn_ok)

        btn_cancel = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_cancel.Name = "btnCancelar"
        btn_cancel.PositionX = 190
        btn_cancel.PositionY = 148
        btn_cancel.Width = 54
        btn_cancel.Height = 14
        btn_cancel.Label = "Cancelar"
        btn_cancel.PushButtonType = 2
        dialog_model.insertByName("btnCancelar", btn_cancel)

        dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", self.uno_context)
        dialog.setModel(dialog_model)
        toolkit = smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", self.uno_context)
        dialog.createPeer(toolkit, None)

        lista = dialog.getControl("lstProductos")
        if coincidencias:
            lista.selectItemPos(0, True)

        return dialog

    def _elegir_producto(self, coincidencias):
        if not coincidencias:
            self._log("No hay coincidencias para mostrar en el selector.")
            return None

        if len(coincidencias) == 1:
            self._log(f"Coincidencia unica detectada: {coincidencias[0][1]!r}")
            return coincidencias[0][1]

        self._log(f"Se encontraron {len(coincidencias)} coincidencias; abriendo selector modal.")
        dialog = self._crear_dialogo_selector(coincidencias)
        self.selector_activo = True
        try:
            resultado = dialog.execute()
            if resultado != 1:
                self._log("Selector cancelado por el usuario.")
                return None

            lista = dialog.getControl("lstProductos")
            indice = int(lista.getSelectedItemPos())
            if indice < 0 or indice >= len(coincidencias):
                self._log(f"Selector sin seleccion valida (indice={indice}).")
                return None

            self._log(f"Selector confirmado con indice={indice}, producto={coincidencias[indice][1]!r}.")
            return coincidencias[indice][1]
        finally:
            self.selector_activo = False
            dialog.dispose()

    def _escribir_producto_en_b4(self, producto):
        with self.sheet_admin.temporary_unlock():
            self.hoja.getCellByPosition(1, 3).String = str(producto)
        self._log(f"Producto escrito en B4: {producto!r}")

        try:
            from calc_focus import enfocar_celda_sin_azul

            enfocar_celda_sin_azul(self.documento, 1, 3)
        except Exception:
            pass

    def _autocompletar_b4(self):
        texto = str(self.hoja.getCellByPosition(1, 3).String).strip()
        if not texto:
            self._log("Autocompletado cancelado: B4 esta vacia.")
            return False

        prefijo = self.ventas_service._normalizar_prefijo_usuario(texto)
        self._log(f"Buscando coincidencias por iniciales: {texto!r} -> {prefijo!r}")
        coincidencias = self.ventas_service.buscar_catalogo_por_iniciales(prefijo, limite=25)
        self._log(f"Coincidencias por iniciales encontradas: {len(coincidencias)}")
        if not coincidencias:
            self._log(f"No se encontraron coincidencias para las iniciales: {prefijo!r}")
            return False

        producto = self._elegir_producto(coincidencias)
        if producto is None:
            self._log("No se aplico ningun producto desde el selector.")
            return True

        self._escribir_producto_en_b4(producto)
        return True

    def keyPressed(self, event):
        if event.KeyCode != UnoKey.TAB:
            return False

        self._log("TAB detectado por el manejador de autocompletado.")

        if self.selector_activo:
            self._log("TAB ignorado: ya hay un selector modal activo.")
            return True

        if not self._celda_b4_activa():
            return False

        self._aceptar_edicion_activa()
        return self._autocompletar_b4()

    def keyReleased(self, event):
        return False

    def disposing(self, event):
        return None
