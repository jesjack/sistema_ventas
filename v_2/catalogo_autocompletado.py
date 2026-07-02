import sqlite3
import unohelper
from com.sun.star.awt import XActionListener

from ventas_service import VentasService

PREPOSICIONES = {
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "y",
    "o",
}


def _normalizar_catalogo(texto):
    return str(texto).strip().lower()


def _formatear_catalogo(texto):
    palabras = []
    for palabra in str(texto).strip().split():
        palabra_limpia = palabra.strip()
        if not palabra_limpia:
            continue
        if palabra_limpia.lower() in PREPOSICIONES:
            palabras.append(palabra_limpia.lower())
        else:
            palabras.append(palabra_limpia[:1].upper() + palabra_limpia[1:].lower())
    return " ".join(palabras)


class _BotonListener(unohelper.Base, XActionListener):
    def __init__(self, callback):
        self._callback = callback

    def actionPerformed(self, _event):
        self._callback()

    def disposing(self, _event):
        pass


class EditorCatalogoAutocompletado:
    def __init__(self, uno_context, ventas_service=None):
        self.uno_context = uno_context
        self.ventas_service = ventas_service or VentasService()
        self._smgr = uno_context.ServiceManager
        self._toolkit = self._smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)

        self._dialog = None
        self._dialog_model = None
        self._list_control = None
        self._edit_control = None
        self._status_control = None
        self._rows = []
        self._listeners = []

    def _crear_dialogo(self):
        model = self._smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", self.uno_context)
        model.PositionX = 120
        model.PositionY = 70
        model.Width = 260
        model.Height = 190
        model.Title = "Catalogo de autocompletado"

        lbl = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        lbl.Name = "lblTitulo"
        lbl.PositionX = 8
        lbl.PositionY = 8
        lbl.Width = 244
        lbl.Height = 12
        lbl.Label = "Productos para autocompletado"
        model.insertByName("lblTitulo", lbl)

        list_model = model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
        list_model.Name = "lstProductos"
        list_model.PositionX = 8
        list_model.PositionY = 22
        list_model.Width = 244
        list_model.Height = 88
        list_model.Dropdown = False
        model.insertByName("lstProductos", list_model)

        lbl_producto = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        lbl_producto.Name = "lblProducto"
        lbl_producto.PositionX = 8
        lbl_producto.PositionY = 116
        lbl_producto.Width = 52
        lbl_producto.Height = 12
        lbl_producto.Label = "Producto"
        model.insertByName("lblProducto", lbl_producto)

        txt = model.createInstance("com.sun.star.awt.UnoControlEditModel")
        txt.Name = "txtProducto"
        txt.PositionX = 62
        txt.PositionY = 114
        txt.Width = 190
        txt.Height = 14
        txt.Text = ""
        model.insertByName("txtProducto", txt)

        btn_cargar = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_cargar.Name = "btnCargar"
        btn_cargar.PositionX = 8
        btn_cargar.PositionY = 136
        btn_cargar.Width = 56
        btn_cargar.Height = 14
        btn_cargar.Label = "Cargar"
        model.insertByName("btnCargar", btn_cargar)

        btn_agregar = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_agregar.Name = "btnAgregar"
        btn_agregar.PositionX = 68
        btn_agregar.PositionY = 136
        btn_agregar.Width = 56
        btn_agregar.Height = 14
        btn_agregar.Label = "Agregar"
        model.insertByName("btnAgregar", btn_agregar)

        btn_editar = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_editar.Name = "btnEditar"
        btn_editar.PositionX = 128
        btn_editar.PositionY = 136
        btn_editar.Width = 56
        btn_editar.Height = 14
        btn_editar.Label = "Editar"
        model.insertByName("btnEditar", btn_editar)

        btn_eliminar = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_eliminar.Name = "btnEliminar"
        btn_eliminar.PositionX = 188
        btn_eliminar.PositionY = 136
        btn_eliminar.Width = 64
        btn_eliminar.Height = 14
        btn_eliminar.Label = "Eliminar"
        model.insertByName("btnEliminar", btn_eliminar)

        status = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        status.Name = "lblStatus"
        status.PositionX = 8
        status.PositionY = 154
        status.Width = 244
        status.Height = 22
        status.MultiLine = True
        status.Label = ""
        model.insertByName("lblStatus", status)

        btn_cerrar = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_cerrar.Name = "btnCerrar"
        btn_cerrar.PositionX = 190
        btn_cerrar.PositionY = 172
        btn_cerrar.Width = 62
        btn_cerrar.Height = 14
        btn_cerrar.Label = "Cerrar"
        btn_cerrar.PushButtonType = 1
        model.insertByName("btnCerrar", btn_cerrar)

        dialog = self._smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", self.uno_context)
        dialog.setModel(model)
        dialog.createPeer(self._toolkit, None)

        self._dialog_model = model
        self._dialog = dialog
        self._list_control = dialog.getControl("lstProductos")
        self._edit_control = dialog.getControl("txtProducto")
        self._status_control = dialog.getControl("lblStatus")

    def _set_status(self, texto):
        self._status_control.getModel().Label = str(texto)

    def _producto_seleccionado(self):
        if not self._rows:
            return None

        try:
            indice = int(self._list_control.getSelectedItemPos())
        except Exception:
            indice = -1

        if indice < 0 or indice >= len(self._rows):
            return None

        return self._rows[indice]

    def _recargar_lista(self, seleccionar_id=None):
        self._rows = self.ventas_service.listar_catalogo_autocompletado()
        nombres = tuple(_formatear_catalogo(nombre) for _id, nombre in self._rows)
        self._list_control.getModel().StringItemList = nombres

        if not self._rows:
            self._set_status("Catalogo vacio. Agrega tu primer producto.")
            return

        indice = 0
        if seleccionar_id is not None:
            for i, (prod_id, _nombre) in enumerate(self._rows):
                if prod_id == seleccionar_id:
                    indice = i
                    break

        self._list_control.selectItemPos(indice, True)

    def _cargar_seleccion(self):
        seleccionado = self._producto_seleccionado()
        if seleccionado is None:
            self._set_status("Selecciona un producto de la lista.")
            return

        _prod_id, nombre = seleccionado
        self._edit_control.getModel().Text = _formatear_catalogo(nombre)
        self._set_status("Producto cargado para edicion.")

    def _agregar(self):
        nombre = _normalizar_catalogo(self._edit_control.getModel().Text)
        if not nombre:
            self._set_status("Escribe un nombre de producto.")
            return

        try:
            prod_id = self.ventas_service.agregar_producto_autocompletado(nombre)
            self._recargar_lista(seleccionar_id=prod_id)
            self._edit_control.getModel().Text = ""
            self._set_status("Producto agregado.")
        except sqlite3.IntegrityError:
            self._set_status("Ese producto ya existe en el catalogo.")
        except Exception as exc:
            self._set_status(f"Error al agregar: {exc}")

    def _editar(self):
        seleccionado = self._producto_seleccionado()
        if seleccionado is None:
            self._set_status("Selecciona un producto para editar.")
            return

        nuevo_nombre = _normalizar_catalogo(self._edit_control.getModel().Text)
        if not nuevo_nombre:
            self._set_status("Escribe el nuevo nombre del producto.")
            return

        prod_id, _nombre = seleccionado
        try:
            actualizado = self.ventas_service.editar_producto_autocompletado(prod_id, nuevo_nombre)
            if actualizado:
                self._recargar_lista(seleccionar_id=prod_id)
                self._set_status("Producto actualizado.")
            else:
                self._set_status("No se encontro el producto seleccionado.")
        except sqlite3.IntegrityError:
            self._set_status("Ya existe otro producto con ese nombre.")
        except Exception as exc:
            self._set_status(f"Error al editar: {exc}")

    def _eliminar(self):
        seleccionado = self._producto_seleccionado()
        if seleccionado is None:
            self._set_status("Selecciona un producto para eliminar.")
            return

        prod_id, nombre = seleccionado
        try:
            eliminado = self.ventas_service.eliminar_producto_autocompletado(prod_id)
            if eliminado:
                self._recargar_lista()
                self._edit_control.getModel().Text = ""
                self._set_status(f"Producto eliminado: {nombre}")
            else:
                self._set_status("No se encontro el producto seleccionado.")
        except Exception as exc:
            self._set_status(f"Error al eliminar: {exc}")

    def _registrar_listener(self, nombre_control, callback):
        listener = _BotonListener(callback)
        self._dialog.getControl(nombre_control).addActionListener(listener)
        self._listeners.append(listener)

    def mostrar(self):
        self._crear_dialogo()
        self._registrar_listener("btnCargar", self._cargar_seleccion)
        self._registrar_listener("btnAgregar", self._agregar)
        self._registrar_listener("btnEditar", self._editar)
        self._registrar_listener("btnEliminar", self._eliminar)
        self._recargar_lista()
        self._dialog.execute()
        self._dialog.dispose()


def abrir_editor_catalogo_autocompletado(uno_context, ventas_service=None):
    editor = EditorCatalogoAutocompletado(uno_context, ventas_service=ventas_service)
    editor.mostrar()
