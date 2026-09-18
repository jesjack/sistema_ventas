import unohelper
from com.sun.star.awt import XActionListener

from services.identidad import USUARIO_PLANTILLA
from services.ventas_service import VentasService

_CANCELADO = object()
_ETIQUETA_PLANTILLA = "NUEVOS USUARIOS (plantilla)"


class _EscuchaBoton(unohelper.Base, XActionListener):
    def __init__(self, al_hacer_clic):
        self._al_hacer_clic = al_hacer_clic

    def actionPerformed(self, event):
        self._al_hacer_clic()

    def disposing(self, event):
        pass


def _crear_dialogo_base(uno_context, titulo, ancho, alto):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 110
    dialog_model.PositionY = 70
    dialog_model.Width = ancho
    dialog_model.Height = alto
    dialog_model.Title = titulo
    return smgr, dialog_model


def _crear_peer(smgr, uno_context, dialog_model):
    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", uno_context)
    dialog.setModel(dialog_model)
    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)
    dialog.createPeer(toolkit, None)
    return dialog


def _agregar_boton_ok_cancel(dialog_model, y, etiqueta_ok="Aceptar"):
    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = dialog_model.Width - 128
    ok_model.PositionY = y
    ok_model.Width = 58
    ok_model.Height = 16
    ok_model.Label = etiqueta_ok
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    cancel_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel_model.Name = "btnCancel"
    cancel_model.PositionX = dialog_model.Width - 66
    cancel_model.PositionY = y
    cancel_model.Width = 58
    cancel_model.Height = 16
    cancel_model.Label = "Cancelar"
    cancel_model.PushButtonType = 2
    dialog_model.insertByName("btnCancel", cancel_model)


def _mostrar_mensaje(uno_context, mensaje, titulo="Aviso"):
    smgr, dialog_model = _crear_dialogo_base(uno_context, titulo, 220, 90)

    texto_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    texto_model.Name = "lblMensaje"
    texto_model.PositionX = 8
    texto_model.PositionY = 10
    texto_model.Width = 204
    texto_model.Height = 40
    texto_model.MultiLine = True
    texto_model.Label = mensaje
    dialog_model.insertByName("lblMensaje", texto_model)

    ok_model = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok_model.Name = "btnOk"
    ok_model.PositionX = 78
    ok_model.PositionY = 58
    ok_model.Width = 60
    ok_model.Height = 16
    ok_model.Label = "Aceptar"
    ok_model.PushButtonType = 1
    ok_model.DefaultButton = True
    dialog_model.insertByName("btnOk", ok_model)

    dialog = _crear_peer(smgr, uno_context, dialog_model)
    try:
        dialog.execute()
    finally:
        dialog.dispose()


def _solicitar_texto(uno_context, titulo, etiqueta, valor_inicial=""):
    smgr, dialog_model = _crear_dialogo_base(uno_context, titulo, 240, 94)

    etiqueta_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    etiqueta_model.Name = "lblEtiqueta"
    etiqueta_model.PositionX = 8
    etiqueta_model.PositionY = 10
    etiqueta_model.Width = 224
    etiqueta_model.Height = 12
    etiqueta_model.MultiLine = True
    etiqueta_model.Label = etiqueta
    dialog_model.insertByName("lblEtiqueta", etiqueta_model)

    edit_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
    edit_model.Name = "txtValor"
    edit_model.PositionX = 8
    edit_model.PositionY = 30
    edit_model.Width = 224
    edit_model.Height = 14
    edit_model.Text = str(valor_inicial)
    dialog_model.insertByName("txtValor", edit_model)

    _agregar_boton_ok_cancel(dialog_model, 68)

    dialog = _crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return None
        return dialog.getControl("txtValor").getModel().Text.strip()
    finally:
        dialog.dispose()


def _solicitar_datos_boton(uno_context, titulo, etiqueta_inicial="", archivo_inicial="", orden_inicial=0):
    smgr, dialog_model = _crear_dialogo_base(uno_context, titulo, 260, 140)

    def _agregar_campo(nombre, y, etiqueta_texto, valor_inicial):
        etiqueta_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        etiqueta_model.Name = f"lbl{nombre}"
        etiqueta_model.PositionX = 8
        etiqueta_model.PositionY = y
        etiqueta_model.Width = 244
        etiqueta_model.Height = 12
        etiqueta_model.Label = etiqueta_texto
        dialog_model.insertByName(f"lbl{nombre}", etiqueta_model)

        edit_model = dialog_model.createInstance("com.sun.star.awt.UnoControlEditModel")
        edit_model.Name = f"txt{nombre}"
        edit_model.PositionX = 8
        edit_model.PositionY = y + 14
        edit_model.Width = 244
        edit_model.Height = 14
        edit_model.Text = str(valor_inicial)
        dialog_model.insertByName(f"txt{nombre}", edit_model)

    _agregar_campo("Etiqueta", 8, "Etiqueta (texto del botón):", etiqueta_inicial)
    _agregar_campo("Archivo", 46, "Archivo en acciones/ (sin .py):", archivo_inicial)
    _agregar_campo("Orden", 84, "Orden (número, menor = primero):", orden_inicial)

    _agregar_boton_ok_cancel(dialog_model, 116, etiqueta_ok="Guardar")

    dialog = _crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return None

        etiqueta = dialog.getControl("txtEtiqueta").getModel().Text.strip()
        archivo = dialog.getControl("txtArchivo").getModel().Text.strip()
        orden_texto = dialog.getControl("txtOrden").getModel().Text.strip()
    finally:
        dialog.dispose()

    if not etiqueta or not archivo:
        return None

    try:
        orden = int(orden_texto) if orden_texto else 0
    except ValueError:
        orden = 0

    return etiqueta, archivo, orden


def _ejecutar_dialogo_con_acciones(uno_context, dialog_model, dialog, mapa_botones, nombre_lista=None):
    accion = {"valor": None}

    def _marcar(valor):
        accion["valor"] = valor
        dialog.endExecute()

    referencias = []
    for nombre_control, valor in mapa_botones.items():
        listener = _EscuchaBoton(lambda valor=valor: _marcar(valor))
        dialog.getControl(nombre_control).addActionListener(listener)
        referencias.append(listener)

    try:
        dialog.execute()
        seleccion = dialog.getControl(nombre_lista).getSelectedItemPos() if nombre_lista else -1
    finally:
        dialog.dispose()

    return accion["valor"], seleccion


def _etiqueta_usuario(nombre_usuario):
    return _ETIQUETA_PLANTILLA if nombre_usuario == USUARIO_PLANTILLA else nombre_usuario


def _listar_usuarios_candidatos(ventas_service):
    # __default__ (la plantilla) siempre primero y con etiqueta amigable;
    # el resto, usuarios reales vistos alguna vez en usuarios_sistema, en orden alfabetico.
    nombres = sorted(
        {str(nombre_usuario).strip().lower() for _id, nombre_usuario, *_resto in ventas_service.listar_usuarios_sistema()}
    )
    nombres = [n for n in nombres if n != USUARIO_PLANTILLA]
    return [USUARIO_PLANTILLA] + nombres


def _solicitar_visibilidad(uno_context, titulo, candidatos, seleccionados_previos):
    seleccionados_previos = set(seleccionados_previos or [])

    alto_checkboxes = 16 * len(candidatos)
    alto_total = 24 + alto_checkboxes + 34
    smgr, dialog_model = _crear_dialogo_base(uno_context, titulo, 260, alto_total)

    y = 8

    def _agregar_checkbox(nombre, etiqueta_texto, marcado):
        nonlocal y
        modelo = dialog_model.createInstance("com.sun.star.awt.UnoControlCheckBoxModel")
        modelo.Name = nombre
        modelo.PositionX = 8
        modelo.PositionY = y
        modelo.Width = 244
        modelo.Height = 14
        modelo.Label = etiqueta_texto
        modelo.TriState = False
        modelo.State = 1 if marcado else 0
        dialog_model.insertByName(nombre, modelo)
        y += 16

    for indice, nombre_usuario in enumerate(candidatos):
        _agregar_checkbox(f"chkUsuario{indice}", _etiqueta_usuario(nombre_usuario), nombre_usuario in seleccionados_previos)

    _agregar_boton_ok_cancel(dialog_model, y + 8, etiqueta_ok="Guardar")

    dialog = _crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return _CANCELADO

        usuarios = []
        for indice, nombre_usuario in enumerate(candidatos):
            if dialog.getControl(f"chkUsuario{indice}").getState() == 1:
                usuarios.append(nombre_usuario)
        return usuarios
    finally:
        dialog.dispose()


def _pantalla_botones(uno_context, botones_service, ventas_service):
    while True:
        botones = botones_service.listar_botones()
        etiquetas = [
            f"{etiqueta} -> {archivo} [{'activo' if activo else 'inactivo'}] (orden {orden})"
            for _id, _nombre_interno, etiqueta, archivo, orden, activo in botones
        ]

        smgr, dialog_model = _crear_dialogo_base(uno_context, "Administrar botones", 320, 210)

        lista_model = dialog_model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
        lista_model.Name = "lstBotones"
        lista_model.PositionX = 8
        lista_model.PositionY = 8
        lista_model.Width = 304
        lista_model.Height = 118
        lista_model.StringItemList = tuple(etiquetas)
        dialog_model.insertByName("lstBotones", lista_model)

        disposicion = (
            ("btnCrear", 8, 134, 70, "Crear"),
            ("btnEditar", 82, 134, 70, "Editar"),
            ("btnEliminar", 156, 134, 70, "Eliminar"),
            ("btnActivar", 8, 154, 100, "Activar/Desactivar"),
            ("btnVisibilidad", 112, 154, 100, "Visibilidad"),
            ("btnCerrar", 216, 154, 96, "Cerrar"),
        )
        for nombre, x, y, ancho, etiqueta_texto in disposicion:
            modelo = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
            modelo.Name = nombre
            modelo.PositionX = x
            modelo.PositionY = y
            modelo.Width = ancho
            modelo.Height = 16
            modelo.Label = etiqueta_texto
            dialog_model.insertByName(nombre, modelo)

        dialog = _crear_peer(smgr, uno_context, dialog_model)
        mapa = {
            "btnCrear": "crear",
            "btnEditar": "editar",
            "btnEliminar": "eliminar",
            "btnActivar": "activar",
            "btnVisibilidad": "visibilidad",
            "btnCerrar": "cerrar",
        }
        valor, seleccion = _ejecutar_dialogo_con_acciones(uno_context, dialog_model, dialog, mapa, "lstBotones")

        if valor in (None, "cerrar"):
            return

        if valor == "crear":
            datos = _solicitar_datos_boton(uno_context, "Nuevo botón")
            if datos is None:
                continue
            etiqueta, archivo, orden = datos
            try:
                botones_service.crear_boton(archivo, etiqueta, archivo, orden)
            except ValueError as exc:
                _mostrar_mensaje(uno_context, str(exc))
            continue

        if seleccion < 0 or seleccion >= len(botones):
            _mostrar_mensaje(uno_context, "Seleccione un botón de la lista primero.")
            continue

        boton_id, _nombre_interno, etiqueta, archivo, orden, activo = botones[seleccion]

        if valor == "editar":
            datos = _solicitar_datos_boton(uno_context, "Editar botón", etiqueta, archivo, orden)
            if datos is None:
                continue
            nueva_etiqueta, nuevo_archivo, nuevo_orden = datos
            botones_service.editar_boton(boton_id, etiqueta=nueva_etiqueta, archivo_accion=nuevo_archivo, orden=nuevo_orden)
            continue

        if valor == "eliminar":
            botones_service.eliminar_boton(boton_id)
            continue

        if valor == "activar":
            botones_service.establecer_activo(boton_id, not activo)
            continue

        if valor == "visibilidad":
            usuarios_actuales = botones_service.listar_visibilidad(boton_id)
            candidatos = _listar_usuarios_candidatos(ventas_service)
            candidatos_completos = candidatos + [u for u in usuarios_actuales if u not in candidatos]
            resultado = _solicitar_visibilidad(uno_context, f"Visibilidad: {etiqueta}", candidatos_completos, usuarios_actuales)
            if resultado is not _CANCELADO:
                botones_service.set_visibilidad(boton_id, resultado)
            continue


def _pantalla_botones_de_usuario(uno_context, botones_service, nombre_usuario):
    etiqueta_pantalla = _etiqueta_usuario(nombre_usuario)

    usuario_id = botones_service.obtener_usuario_id(nombre_usuario)
    botones = botones_service.listar_botones()
    visibles_ids = {
        boton_id
        for boton_id, _et, _ar, _or in botones_service.listar_botones_visibles_para(usuario_id, solo_activos=False)
    }

    smgr, dialog_model = _crear_dialogo_base(uno_context, f"Botones de: {etiqueta_pantalla}", 280, 40 + 16 * len(botones) + 34)

    y = 8
    for indice, (boton_id, _ni, etiqueta, _ar, _or, activo) in enumerate(botones):
        modelo = dialog_model.createInstance("com.sun.star.awt.UnoControlCheckBoxModel")
        modelo.Name = f"chkBoton{indice}"
        modelo.PositionX = 8
        modelo.PositionY = y
        modelo.Width = 244
        modelo.Height = 14
        modelo.Label = f"{etiqueta}" + ("" if activo else " (inactivo)")
        modelo.TriState = False
        modelo.State = 1 if boton_id in visibles_ids else 0
        dialog_model.insertByName(f"chkBoton{indice}", modelo)
        y += 16

    _agregar_boton_ok_cancel(dialog_model, y + 8, etiqueta_ok="Guardar")

    dialog = _crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return

        for indice, (boton_id, _ni, _et, _ar, _or, _ac) in enumerate(botones):
            marcado = dialog.getControl(f"chkBoton{indice}").getState() == 1
            ya_incluido = boton_id in visibles_ids
            if marcado == ya_incluido:
                continue

            visibilidad_actual = botones_service.listar_visibilidad(boton_id)
            nueva = [u for u in visibilidad_actual if u != nombre_usuario]
            if marcado:
                nueva.append(nombre_usuario)
            botones_service.set_visibilidad(boton_id, nueva)
    finally:
        dialog.dispose()


def _pantalla_usuarios(uno_context, botones_service, ventas_service):
    while True:
        usuarios = _listar_usuarios_candidatos(ventas_service)
        etiquetas = [_etiqueta_usuario(nombre) for nombre in usuarios]

        smgr, dialog_model = _crear_dialogo_base(uno_context, "Usuarios y accesos", 260, 190)

        lista_model = dialog_model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
        lista_model.Name = "lstUsuarios"
        lista_model.PositionX = 8
        lista_model.PositionY = 8
        lista_model.Width = 244
        lista_model.Height = 128
        lista_model.StringItemList = tuple(etiquetas)
        dialog_model.insertByName("lstUsuarios", lista_model)

        for nombre, x, etiqueta_texto in (("btnBotones", 8, "Administrar botones"), ("btnCerrar", 176, "Cerrar")):
            modelo = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
            modelo.Name = nombre
            modelo.PositionX = x
            modelo.PositionY = 144
            modelo.Width = 76 if nombre == "btnCerrar" else 160
            modelo.Height = 16
            modelo.Label = etiqueta_texto
            dialog_model.insertByName(nombre, modelo)

        dialog = _crear_peer(smgr, uno_context, dialog_model)
        mapa = {"btnBotones": "botones", "btnCerrar": "cerrar"}
        valor, seleccion = _ejecutar_dialogo_con_acciones(uno_context, dialog_model, dialog, mapa, "lstUsuarios")

        if valor in (None, "cerrar"):
            return

        if valor == "botones":
            if seleccion < 0 or seleccion >= len(usuarios):
                _mostrar_mensaje(uno_context, "Seleccione un usuario de la lista primero.")
                continue
            _pantalla_botones_de_usuario(uno_context, botones_service, usuarios[seleccion])
            continue


def _pantalla_menu_principal(uno_context):
    smgr, dialog_model = _crear_dialogo_base(uno_context, "Administrar admins", 220, 130)

    lista_model = dialog_model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
    lista_model.Name = "lstMenu"
    lista_model.PositionX = 8
    lista_model.PositionY = 8
    lista_model.Width = 204
    lista_model.Height = 70
    lista_model.StringItemList = ("Usuarios y accesos", "Administrar botones")
    dialog_model.insertByName("lstMenu", lista_model)

    _agregar_boton_ok_cancel(dialog_model, 88, etiqueta_ok="Entrar")
    dialog_model.getByName("btnCancel").Label = "Cerrar"

    dialog = _crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return None
        seleccion = dialog.getControl("lstMenu").getSelectedItemPos()
    finally:
        dialog.dispose()

    if seleccion == 0:
        return "usuarios"
    if seleccion == 1:
        return "botones"
    return None


def abrir_panel_administracion(uno_context, botones_service, usuario_actual):
    ventas_service = VentasService()

    while True:
        opcion = _pantalla_menu_principal(uno_context)
        if opcion is None:
            return
        if opcion == "usuarios":
            _pantalla_usuarios(uno_context, botones_service, ventas_service)
        elif opcion == "botones":
            _pantalla_botones(uno_context, botones_service, ventas_service)
