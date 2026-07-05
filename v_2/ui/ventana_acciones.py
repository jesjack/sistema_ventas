import getpass
import os
import pwd
import unohelper
from com.sun.star.awt import XActionListener, XFocusListener, XMouseListener, XTopWindowListener, XWindowListener
import unicodedata
import threading
import time


_listener_refs = []


def _obtener_area_referencia(uno_context):
    """
    Intenta obtener el rectangulo util de la ventana actual de Calc.
    Si no se puede, usa un area de respaldo para evitar fallos.
    """
    try:
        smgr = uno_context.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", uno_context)
        documento = desktop.getCurrentComponent()
        if documento is not None and hasattr(documento, "getCurrentController"):
            controlador = documento.getCurrentController()
            if controlador is not None and hasattr(controlador, "getFrame"):
                frame = controlador.getFrame()
                ventana = None
                if hasattr(frame, "getContainerWindow"):
                    ventana = frame.getContainerWindow()
                if ventana is None and hasattr(frame, "getComponentWindow"):
                    ventana = frame.getComponentWindow()
                if ventana is not None and hasattr(ventana, "getPosSize"):
                    ps = ventana.getPosSize()
                    return (
                        int(getattr(ps, "X", 0)),
                        int(getattr(ps, "Y", 0)),
                        max(int(getattr(ps, "Width", 0)), 1),
                        max(int(getattr(ps, "Height", 0)), 1),
                    )
    except Exception:
        pass

    # Respaldo razonable si no hay acceso a la ventana activa.
    return (0, 0, 1280, 720)


class VentanaAcciones:
    def __init__(self, uno_context, titulo="Acciones", ancho=260, alto=90, padding=10, gap_y=8, boton_alto=18, al_recuperar_foco=None, registrar_atajo=None, posicion=None, margen=12):
        self.uno_context = uno_context
        self._smgr = uno_context.ServiceManager
        self._dialog_model = self._smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
        self._dialog_model.PositionX = 0
        self._dialog_model.PositionY = 0
        self._dialog_model.Width = max(ancho, 140)
        self._dialog_model.Height = max(alto, 60)
        self._dialog_model.Title = titulo
        self._dialog = self._smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", uno_context)
        self._toolkit = self._smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)
        self._botones_pendientes = []
        self._peer_creado = False
        self._al_recuperar_foco = al_recuperar_foco
        self._registrar_atajo = registrar_atajo
        self._atajos_usados = set()
        self._ultimas_ejecuciones = {}
        self._ejecuciones_en_curso = set()
        self._ejecuciones_lock = threading.Lock()
        self._posicion = posicion
        self._margen = max(int(margen), 0)
        self._padding = int(padding)
        self._gap_y = int(gap_y)
        self._boton_alto = int(boton_alto)
        self._boton_ancho = max(int(ancho) - (2 * self._padding), 48)
        self._usuario_actual = self._obtener_usuario_actual()

    def _obtener_usuario_actual(self):
        for clave in ("SUDO_USER", "PKEXEC_UID"):
            valor = os.environ.get(clave)
            if not valor:
                continue

            if clave == "PKEXEC_UID":
                try:
                    valor = pwd.getpwuid(int(valor)).pw_name
                except Exception:
                    continue

            valor = str(valor).strip()
            if valor and valor.lower() != "root":
                return self._normalizar_texto(valor).strip().lower()

        for obtenedor in (getpass.getuser, os.getlogin):
            try:
                nombre = obtenedor()
                if nombre:
                    return self._normalizar_texto(nombre).strip().lower()
            except Exception:
                pass

        for clave in ("USERNAME", "USER"):
            valor = os.environ.get(clave)
            if valor:
                return self._normalizar_texto(valor).strip().lower()

        return "desconocido"

    def _aplicar_anclaje(self):
        if self._posicion is None:
            return

        posicion = str(self._posicion).strip().lower()
        if posicion not in {"superior_izquierda", "superior_derecha", "inferior_izquierda", "inferior_derecha"}:
            return

        area_x, area_y, area_ancho, area_alto = _obtener_area_referencia(self.uno_context)
        ancho = int(self._dialog_model.Width)
        alto = int(self._dialog_model.Height)

        if "derecha" in posicion:
            x = area_x + area_ancho - ancho - self._margen
        else:
            x = area_x + self._margen

        if "inferior" in posicion:
            y = area_y + area_alto - alto - self._margen
        else:
            y = area_y + self._margen

        self._dialog_model.PositionX = max(int(x), 0)
        self._dialog_model.PositionY = max(int(y), 0)

    def _ancho_texto_boton(self, texto):
        return max(46, min(220, 10 + (len(str(texto)) * 5)))

    def _normalizar_texto(self, texto):
        texto_normalizado = unicodedata.normalize("NFKD", str(texto))
        return "".join(char for char in texto_normalizado if not unicodedata.combining(char))

    def _sufijo_atajo(self, tecla):
        return f"  (Alt+{tecla.upper()})" if tecla else ""

    def _obtener_atajo_disponible(self, texto):
        texto_normalizado = self._normalizar_texto(texto).upper()
        candidatos = []
        for caracter in texto_normalizado:
            if caracter.isalpha() and caracter not in candidatos:
                candidatos.append(caracter)

        for caracter in candidatos:
            if caracter not in self._atajos_usados:
                self._atajos_usados.add(caracter)
                return caracter

        for caracter in texto_normalizado:
            if caracter.isdigit() and caracter not in self._atajos_usados:
                self._atajos_usados.add(caracter)
                return caracter

        for caracter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            if caracter not in self._atajos_usados:
                self._atajos_usados.add(caracter)
                return caracter

        return None

    def _actualizar_dimension_dialogo(self):
        cantidad_botones = len(self._botones_pendientes)
        alto_total = self._padding * 2
        if cantidad_botones > 0:
            alto_total += cantidad_botones * self._boton_alto
            alto_total += (cantidad_botones - 1) * self._gap_y

        boton_ancho_maximo = self._boton_ancho
        for _, _, texto, _boton_model in self._botones_pendientes:
            boton_ancho_maximo = max(boton_ancho_maximo, self._ancho_texto_boton(texto))

        for indice, (nombre, _accion, _texto, boton_model) in enumerate(self._botones_pendientes):
            boton_model.PositionX = self._padding
            boton_model.PositionY = self._padding + (indice * (self._boton_alto + self._gap_y))
            boton_model.Width = boton_ancho_maximo
            boton_model.Height = self._boton_alto

        self._boton_ancho = boton_ancho_maximo
        ancho_total = boton_ancho_maximo + (2 * self._padding)
        self._dialog_model.Width = max(ancho_total, self._padding * 2 + 48)
        self._dialog_model.Height = max(alto_total, 60)

    def _crear_ejecutor_accion(self, accion_id, accion):
        def ejecutar_accion():
            tiempo_actual = time.monotonic()
            with self._ejecuciones_lock:
                ultima_ejecucion = self._ultimas_ejecuciones.get(accion_id, 0.0)
                if accion_id in self._ejecuciones_en_curso:
                    return
                if tiempo_actual - ultima_ejecucion < 0.25:
                    return
                self._ejecuciones_en_curso.add(accion_id)
                self._ultimas_ejecuciones[accion_id] = tiempo_actual

            try:
                accion()
            finally:
                with self._ejecuciones_lock:
                    self._ejecuciones_en_curso.discard(accion_id)

        return ejecutar_accion

    def _normalizar_listado_usuarios(self, usuarios):
        if usuarios is None:
            return ["all"]

        if isinstance(usuarios, str):
            usuarios = [usuarios]

        return [self._normalizar_texto(usuario).strip().lower() for usuario in usuarios if str(usuario).strip()]

    def _boton_es_visible_para_usuario(self, usuarios):
        usuarios_normalizados = self._normalizar_listado_usuarios(usuarios)
        if not usuarios_normalizados or "all" in usuarios_normalizados:
            return True
        return self._usuario_actual in usuarios_normalizados

    def agregar_boton(self, texto, accion, usuarios=None, nombre=None):
        if nombre is None and isinstance(usuarios, str):
            nombre = usuarios
            usuarios = None

        if not self._boton_es_visible_para_usuario(usuarios):
            return self

        nombre = nombre or f"btnAccion{len(self._botones_pendientes) + 1}"
        indice = len(self._botones_pendientes)
        posicion_y = self._padding + (indice * (self._boton_alto + self._gap_y))
        ejecutar_accion = self._crear_ejecutor_accion(nombre, accion)
        atajo = self._obtener_atajo_disponible(texto)
        texto_mostrado = f"{texto}{self._sufijo_atajo(atajo)}"

        boton_ancho = max(self._boton_ancho, self._ancho_texto_boton(texto_mostrado))
        posicion_x = self._padding

        boton_model = self._dialog_model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        boton_model.Name = nombre
        boton_model.PositionX = posicion_x
        boton_model.PositionY = posicion_y
        boton_model.Width = boton_ancho
        boton_model.Height = self._boton_alto
        boton_model.Label = texto_mostrado
        self._dialog_model.insertByName(nombre, boton_model)
        self._botones_pendientes.append((nombre, ejecutar_accion, texto_mostrado, boton_model))
        if atajo is not None and self._registrar_atajo is not None:
            self._registrar_atajo(f"alt+{atajo.lower()}", ejecutar_accion)
        self._actualizar_dimension_dialogo()
        return self

    def _asegurar_peer(self):
        if self._peer_creado:
            return

        self._dialog.setModel(self._dialog_model)
        self._dialog.createPeer(self._toolkit, None)
        self._peer_creado = True

        class _AccionYCierreListener(unohelper.Base, XActionListener, XFocusListener, XMouseListener, XTopWindowListener, XWindowListener):
            def __init__(self, accion_fn, recuperar_foco_fn):
                self._accion_fn = accion_fn
                self._recuperar_foco_fn = recuperar_foco_fn

            def _recuperar_foco(self):
                if self._recuperar_foco_fn is not None:
                    self._recuperar_foco_fn()

            def actionPerformed(self, event):
                try:
                    self._accion_fn()
                finally:
                    self._recuperar_foco()

            def focusGained(self, event):
                pass

            def focusLost(self, event):
                self._recuperar_foco()

            def mouseEntered(self, event):
                pass

            def mouseExited(self, event):
                self._recuperar_foco()

            def mousePressed(self, event):
                pass

            def mouseReleased(self, event):
                pass

            def windowActivated(self, event):
                pass

            def windowClosed(self, event):
                self._recuperar_foco()

            def windowClosing(self, event):
                self._recuperar_foco()

            def windowDeactivated(self, event):
                self._recuperar_foco()

            def windowHidden(self, event):
                self._recuperar_foco()

            def windowMinimized(self, event):
                pass

            def windowMoved(self, event):
                pass

            def windowNormalized(self, event):
                pass

            def windowOpened(self, event):
                pass

            def windowResized(self, event):
                pass

            def windowShown(self, event):
                pass

            def disposing(self, event):
                pass

        listener_dialogo = _AccionYCierreListener(lambda: None, self._al_recuperar_foco)
        if hasattr(self._dialog, "addMouseListener"):
            self._dialog.addMouseListener(listener_dialogo)
        if hasattr(self._dialog, "addFocusListener"):
            self._dialog.addFocusListener(listener_dialogo)
        if hasattr(self._dialog, "addWindowListener"):
            self._dialog.addWindowListener(listener_dialogo)
        if hasattr(self._dialog, "addTopWindowListener"):
            self._dialog.addTopWindowListener(listener_dialogo)

        for nombre, accion, _texto, _boton_model in self._botones_pendientes:
            boton = self._dialog.getControl(nombre)
            listener = _AccionYCierreListener(accion, self._al_recuperar_foco)
            boton.addActionListener(listener)
            _listener_refs.append(listener)
        _listener_refs.append(listener_dialogo)

    def mostrar(self):
        self._aplicar_anclaje()
        self._asegurar_peer()
        self._dialog.setVisible(True)
        if self._al_recuperar_foco is not None:
            # Se difiere unos milisegundos para evitar que el dialogo vuelva a robar el foco.
            threading.Timer(0.05, self._al_recuperar_foco).start()
        return self._dialog


def crear_ventana_acciones(uno_context, titulo="Acciones", x=0, y=0, ancho=260, alto=90, padding=10, gap_y=8, boton_alto=18, al_recuperar_foco=None, registrar_atajo=None, posicion=None, margen=12):
    ventana = VentanaAcciones(
        uno_context,
        titulo=titulo,
        ancho=ancho,
        alto=alto,
        padding=padding,
        gap_y=gap_y,
        boton_alto=boton_alto,
        al_recuperar_foco=al_recuperar_foco,
        registrar_atajo=registrar_atajo,
        posicion=posicion,
        margen=margen,
    )
    ventana._dialog_model.PositionX = int(x)
    ventana._dialog_model.PositionY = int(y)
    return ventana