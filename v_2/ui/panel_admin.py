from dialogs._base import EscuchaAccion, EscuchaCasilla, crear_peer
from services.identidad import USUARIO_PLANTILLA
from services.usuarios_service import UsuariosService

_ETIQUETA_PLANTILLA = "NUEVOS USUARIOS (plantilla)"


def _crear_dialogo_base(uno_context, titulo, ancho, alto):
    smgr = uno_context.ServiceManager
    dialog_model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
    dialog_model.PositionX = 110
    dialog_model.PositionY = 70
    dialog_model.Width = ancho
    dialog_model.Height = alto
    dialog_model.Title = titulo
    return smgr, dialog_model


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

    dialog = crear_peer(smgr, uno_context, dialog_model)
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

    dialog = crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return None
        return dialog.getControl("txtValor").getModel().Text.strip()
    finally:
        dialog.dispose()


def _solicitar_datos_boton(uno_context, titulo, etiqueta_inicial="", archivo_inicial=""):
    # Sin campo de orden: se reordena con las flechas de la matriz (ver _mover_boton), nunca
    # escribiendo un numero a mano.
    smgr, dialog_model = _crear_dialogo_base(uno_context, titulo, 260, 108)

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

    _agregar_boton_ok_cancel(dialog_model, 84, etiqueta_ok="Guardar")

    dialog = crear_peer(smgr, uno_context, dialog_model)
    try:
        resultado = dialog.execute()
        if resultado != 1:
            return None

        etiqueta = dialog.getControl("txtEtiqueta").getModel().Text.strip()
        archivo = dialog.getControl("txtArchivo").getModel().Text.strip()
    finally:
        dialog.dispose()

    if not etiqueta or not archivo:
        return None

    return etiqueta, archivo


def _ejecutar_dialogo_con_acciones(uno_context, dialog_model, dialog, mapa_botones, nombre_lista=None):
    accion = {"valor": None}

    def _marcar(valor):
        accion["valor"] = valor
        dialog.endExecute()

    referencias = []
    for nombre_control, valor in mapa_botones.items():
        listener = EscuchaAccion(lambda valor=valor: _marcar(valor))
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


def _listar_usuarios_candidatos(usuarios_service):
    # __default__ (la plantilla) siempre primero y con etiqueta amigable;
    # el resto, usuarios reales vistos alguna vez en usuarios_sistema, en orden alfabetico.
    nombres = sorted(
        {str(nombre_usuario).strip().lower() for _id, nombre_usuario, *_resto in usuarios_service.listar_usuarios_sistema()}
    )
    nombres = [n for n in nombres if n != USUARIO_PLANTILLA]
    return [USUARIO_PLANTILLA] + nombres


def _mover_boton(botones_service, botones, indice, direccion):
    """Intercambia el botón en `indice` con su vecino (direccion=-1 izquierda, +1 derecha) y
    renumera TODOS los botones 0..n-1 según el nuevo orden visual -- no solo los dos que se
    mueven: si dos botones comparten el mismo `orden` (empate en la base real), intercambiar
    solo esos dos valores no cambiaria nada. Renumerar todos de una vez deshace cualquier
    empate de paso y deja las flechas funcionando siempre."""
    nuevo_indice = indice + direccion
    if nuevo_indice < 0 or nuevo_indice >= len(botones):
        return

    reordenados = list(botones)
    reordenados[indice], reordenados[nuevo_indice] = reordenados[nuevo_indice], reordenados[indice]
    for nueva_posicion, boton in enumerate(reordenados):
        botones_service.editar_boton(boton[0], orden=nueva_posicion)


def _menu_editar_boton(uno_context, boton):
    _boton_id, _nombre_interno, etiqueta, _archivo, _orden, _activo = boton
    smgr, dialog_model = _crear_dialogo_base(uno_context, etiqueta, 200, 112)

    titulo_model = dialog_model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    titulo_model.Name = "lblTitulo"
    titulo_model.PositionX = 8
    titulo_model.PositionY = 8
    titulo_model.Width = 184
    titulo_model.Height = 14
    titulo_model.Label = etiqueta
    dialog_model.insertByName("lblTitulo", titulo_model)

    for nombre, y, etiqueta_texto in (("btnEditar", 28, "Editar"), ("btnEliminar", 52, "Eliminar"), ("btnCerrar", 76, "Cerrar")):
        modelo = dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        modelo.Name = nombre
        modelo.PositionX = 8
        modelo.PositionY = y
        modelo.Width = 184
        modelo.Height = 18
        modelo.Label = etiqueta_texto
        dialog_model.insertByName(nombre, modelo)

    dialog = crear_peer(smgr, uno_context, dialog_model)
    mapa = {"btnEditar": "editar", "btnEliminar": "eliminar", "btnCerrar": "cerrar"}
    valor, _seleccion = _ejecutar_dialogo_con_acciones(uno_context, dialog_model, dialog, mapa)
    return valor


ANCHO_COL_USUARIO = 132
ANCHO_COL_BOTON = 28  # angosta: el nombre va en vertical (una letra por línea), no de lado
ALTO_BLOQUE_FLECHAS = 42  # ◀ + casilla de activo + ▶, apilados (no caben lado a lado en 28px)
ALTO_POR_LETRA = 11
ALTO_FILA = 18
_X0 = 8
_Y0 = 8


def _pantalla_botones(uno_context, botones_service, usuarios_service):
    """Matriz de botones (columnas) x usuarios (filas), con una casilla por celda para la
    visibilidad de ese botón para ese usuario. Columnas angostas -- el nombre del botón va en
    vertical, una letra por línea, no de lado -- para que la matriz quepa en pantalla sin importar
    cuántos botones haya; eso era justo lo que se perdía con columnas anchas. En el encabezado de
    cada columna: flechas ◀/▶ para reordenar (intercambian con el vecino, nunca un número a mano)
    y una casilla de activo/inactivo (desmarcarla apaga -- y deshabilita -- todas las casillas de
    esa columna), apiladas porque no caben lado a lado en una columna tan angosta. Un clic en el
    nombre abre Editar/Eliminar."""
    while True:
        botones = botones_service.listar_botones()

        candidatos = _listar_usuarios_candidatos(usuarios_service)
        visibilidad_por_boton = {boton[0]: set(botones_service.listar_visibilidad(boton[0])) for boton in botones}
        extra = sorted({u for visibles in visibilidad_por_boton.values() for u in visibles if u not in candidatos})
        usuarios_filas = candidatos + extra

        letras_max = max((len(boton[2]) for boton in botones), default=0)
        alto_encabezado = ALTO_BLOQUE_FLECHAS + letras_max * ALTO_POR_LETRA + 4

        ancho = _X0 * 2 + ANCHO_COL_USUARIO + max(1, len(botones)) * ANCHO_COL_BOTON
        alto_grilla = alto_encabezado + len(usuarios_filas) * ALTO_FILA
        alto = _Y0 * 2 + alto_grilla + 8 + 20
        smgr, dialog_model = _crear_dialogo_base(uno_context, "Administrar botones", ancho, alto)

        def _control(tipo, nombre, x, y, ancho_control, alto_control, **propiedades):
            modelo = dialog_model.createInstance(tipo)
            modelo.Name = nombre
            modelo.PositionX = x
            modelo.PositionY = y
            modelo.Width = ancho_control
            modelo.Height = alto_control
            for propiedad, valor in propiedades.items():
                setattr(modelo, propiedad, valor)
            dialog_model.insertByName(nombre, modelo)
            return modelo

        # Encabezados de fila (usuarios), columna izquierda. Se alinean con el PIE de la zona de
        # encabezados de columna, no con su tope: los nombres de usuario quedan a la altura de las
        # casillas, no a medio bloque de letras verticales.
        y_grilla = _Y0 + alto_encabezado
        for j, nombre_usuario in enumerate(usuarios_filas):
            _control(
                "com.sun.star.awt.UnoControlFixedTextModel", f"lbl_usuario_{j}",
                _X0, y_grilla + j * ALTO_FILA + 2, ANCHO_COL_USUARIO - 4, ALTO_FILA,
                Label=_etiqueta_usuario(nombre_usuario),
            )

        # Encabezados de columna (botones): flechas y casilla de activo apiladas (no caben lado a
        # lado en una columna de ANCHO_COL_BOTON), y el nombre en vertical debajo -- una letra por
        # línea, alineado al PIE del bloque para que quede pegado a la fila de casillas de abajo
        # sin importar cuán corto sea el nombre.
        for i, boton in enumerate(botones):
            boton_id, _ni, etiqueta, _ar, _orden, activo = boton
            x = _X0 + ANCHO_COL_USUARIO + i * ANCHO_COL_BOTON

            _control(
                "com.sun.star.awt.UnoControlButtonModel", f"btn_izq_{i}",
                x, _Y0, ANCHO_COL_BOTON, 14, Label="◀", Enabled=(i > 0),
            )
            _control(
                "com.sun.star.awt.UnoControlCheckBoxModel", f"chk_activo_{i}",
                x + (ANCHO_COL_BOTON - 16) // 2, _Y0 + 14, 16, 14, TriState=False, State=1 if activo else 0,
            )
            _control(
                "com.sun.star.awt.UnoControlButtonModel", f"btn_der_{i}",
                x, _Y0 + 28, ANCHO_COL_BOTON, 14, Label="▶", Enabled=(i < len(botones) - 1),
            )
            # Boton, no etiqueta: un XMouseListener (para detectar doble clic) no entrega NINGUN
            # evento en este toolkit -- comprobado con tres controles distintos (etiqueta, boton,
            # campo), ni siquiera mouseEntered. Un clic simple con ActionListener si es confiable
            # (ya probado hoy con las flechas y las casillas), asi que el nombre abre el menu de
            # Editar/Eliminar con un solo clic, no con doble.
            alto_nombre = len(etiqueta) * ALTO_POR_LETRA
            _control(
                "com.sun.star.awt.UnoControlButtonModel", f"btn_nombre_{i}",
                x, y_grilla - alto_nombre, ANCHO_COL_BOTON, alto_nombre,
                MultiLine=True, Label="\n".join(etiqueta),
            )

            # Casillas de visibilidad de esta columna.
            visibles = visibilidad_por_boton[boton_id]
            for j, nombre_usuario in enumerate(usuarios_filas):
                _control(
                    "com.sun.star.awt.UnoControlCheckBoxModel", f"chk_v_{i}_{j}",
                    x + (ANCHO_COL_BOTON - 16) // 2, y_grilla + j * ALTO_FILA, 16, 16,
                    TriState=False, State=1 if nombre_usuario in visibles else 0, Enabled=bool(activo),
                )

        y_botones = _Y0 + alto_grilla + 8
        _control("com.sun.star.awt.UnoControlButtonModel", "btnCrear", _X0, y_botones, 100, 18, Label="Crear botón")
        _control("com.sun.star.awt.UnoControlButtonModel", "btnCerrar", ancho - _X0 - 76, y_botones, 76, 18, Label="Cerrar", PushButtonType=2)

        dialog = crear_peer(smgr, uno_context, dialog_model)
        accion = {"tipo": "cerrar", "boton": None}
        referencias = []

        def _terminar(tipo, boton=None):
            accion["tipo"] = tipo
            accion["boton"] = boton
            dialog.endExecute()

        def _crear_movedor(i, direccion):
            def _mover():
                _mover_boton(botones_service, botones, i, direccion)
                _terminar("recargar")

            return _mover

        for i, boton in enumerate(botones):
            referencias.append(EscuchaAccion(_crear_movedor(i, -1)))
            dialog.getControl(f"btn_izq_{i}").addActionListener(referencias[-1])
            referencias.append(EscuchaAccion(_crear_movedor(i, 1)))
            dialog.getControl(f"btn_der_{i}").addActionListener(referencias[-1])

            referencias.append(EscuchaAccion(lambda boton=boton: _terminar("editar_boton", boton)))
            dialog.getControl(f"btn_nombre_{i}").addActionListener(referencias[-1])

            def _al_cambiar_activo(marcada, i=i, boton_id=boton[0]):
                botones_service.establecer_activo(boton_id, marcada)
                for j in range(len(usuarios_filas)):
                    dialog.getControl(f"chk_v_{i}_{j}").getModel().Enabled = marcada

            referencias.append(EscuchaCasilla(_al_cambiar_activo))
            dialog.getControl(f"chk_activo_{i}").addItemListener(referencias[-1])

            for j, nombre_usuario in enumerate(usuarios_filas):
                def _al_cambiar_visibilidad(marcada, boton_id=boton[0], nombre_usuario=nombre_usuario):
                    visibles = visibilidad_por_boton[boton_id]
                    visibles.add(nombre_usuario) if marcada else visibles.discard(nombre_usuario)
                    botones_service.set_visibilidad(boton_id, list(visibles))

                referencias.append(EscuchaCasilla(_al_cambiar_visibilidad))
                dialog.getControl(f"chk_v_{i}_{j}").addItemListener(referencias[-1])

        referencias.append(EscuchaAccion(lambda: _terminar("crear")))
        dialog.getControl("btnCrear").addActionListener(referencias[-1])

        try:
            dialog.execute()
        finally:
            dialog.dispose()

        # accion["tipo"] queda en su valor por defecto ("cerrar") si se cerró con el botón
        # Cerrar (PushButtonType=CANCELAR: UNO lo maneja solo, sin pasar por ningún listener
        # nuestro) o con la X de la ventana; cualquier otro camino lo sobreescribe via _terminar.
        tipo = accion["tipo"]

        if tipo == "cerrar":
            return

        if tipo == "crear":
            datos = _solicitar_datos_boton(uno_context, "Nuevo botón")
            if datos is not None:
                etiqueta, archivo = datos
                try:
                    botones_service.crear_boton(archivo, etiqueta, archivo, orden=len(botones))
                except ValueError as exc:
                    _mostrar_mensaje(uno_context, str(exc))
            continue

        if tipo == "editar_boton":
            boton_id, _ni, etiqueta, archivo, _orden, _activo = accion["boton"]
            opcion = _menu_editar_boton(uno_context, accion["boton"])
            if opcion == "editar":
                datos = _solicitar_datos_boton(uno_context, "Editar botón", etiqueta, archivo)
                if datos is not None:
                    nueva_etiqueta, nuevo_archivo = datos
                    botones_service.editar_boton(boton_id, etiqueta=nueva_etiqueta, archivo_accion=nuevo_archivo)
            elif opcion == "eliminar":
                botones_service.eliminar_boton(boton_id)
            continue

        # "recargar": las flechas ya aplicaron el cambio; solo falta reconstruir la matriz.
        continue


def abrir_panel_administracion(uno_context, botones_service, usuario_actual):
    # La matriz (visibilidad por casilla, activo/inactivo en el encabezado) ya cubre todo lo que
    # hacían "Usuarios y accesos"/"Botones de: <usuario>" -- de a un usuario a la vez, botón por
    # botón -- así que se quitaron: no había nada más que ese menú ofreciera. El botón
    # "ADMINISTRAR ADMINS" de la hoja abre la matriz directo, sin un paso intermedio de elegir.
    usuarios_service = UsuariosService()
    _pantalla_botones(uno_context, botones_service, usuarios_service)
