import os
import shutil
import subprocess
import threading
import traceback

import unohelper
from com.sun.star.awt import XFocusListener, XTopWindowListener, XWindowListener  # pyright: ignore[reportMissingImports]
from com.sun.star.frame import XFrameActionListener  # pyright: ignore[reportMissingImports]
from com.sun.star.frame.FrameAction import (  # pyright: ignore[reportMissingImports]
    COMPONENT_DETACHING,
    FRAME_ACTIVATED,
    FRAME_DEACTIVATING,
    FRAME_UI_ACTIVATED,
    FRAME_UI_DEACTIVATING,
)


_FOCO_CALC = None
_LISTENER_REFS = []
_FOCO_LOCK = threading.Lock()


def _registrar_error_foco(contexto, exc):
    print(f"[calc_focus] {contexto}: {exc}")
    print(traceback.format_exc())


def _establecer_estado_foco(valor):
    global _FOCO_CALC
    with _FOCO_LOCK:
        _FOCO_CALC = None if valor is None else bool(valor)


def _obtener_estado_foco():
    with _FOCO_LOCK:
        return _FOCO_CALC


def registrar_seguimiento_foco_calc(documento):
    """
    Registra listeners nativos para mantener el estado de foco de Calc.
    """
    try:
        controlador = documento.getCurrentController()
        if controlador is None:
            return False

        frame = controlador.getFrame()
        if frame is None:
            return False

        ventana = None
        if hasattr(frame, "getComponentWindow"):
            ventana = frame.getComponentWindow()
        if ventana is None and hasattr(frame, "getContainerWindow"):
            ventana = frame.getContainerWindow()

        if ventana is None:
            return False

        try:
            if hasattr(ventana, "hasFocus"):
                _establecer_estado_foco(ventana.hasFocus())
            else:
                _establecer_estado_foco(None)
        except Exception as exc:
            _registrar_error_foco("No se pudo leer el foco inicial de Calc", exc)
            _establecer_estado_foco(None)

        class _ListenerFoco(unohelper.Base, XFocusListener, XTopWindowListener, XWindowListener, XFrameActionListener):
            def frameAction(self, event):
                accion = getattr(event, "Action", None)
                if accion in (FRAME_ACTIVATED, FRAME_UI_ACTIVATED):
                    _establecer_estado_foco(True)
                elif accion in (FRAME_DEACTIVATING, FRAME_UI_DEACTIVATING, COMPONENT_DETACHING):
                    _establecer_estado_foco(False)

            def focusGained(self, event):
                _establecer_estado_foco(True)

            def focusLost(self, event):
                _establecer_estado_foco(False)

            def windowActivated(self, event):
                _establecer_estado_foco(True)

            def windowDeactivated(self, event):
                _establecer_estado_foco(False)

            def windowHidden(self, event):
                _establecer_estado_foco(False)

            def windowMinimized(self, event):
                _establecer_estado_foco(False)

            def windowClosed(self, event):
                _establecer_estado_foco(False)

            def windowClosing(self, event):
                _establecer_estado_foco(False)

            def windowOpened(self, event):
                pass

            def windowMoved(self, event):
                pass

            def windowNormalized(self, event):
                _establecer_estado_foco(True)

            def windowResized(self, event):
                pass

            def windowShown(self, event):
                _establecer_estado_foco(True)

            def disposing(self, event):
                pass

        listener = _ListenerFoco()
        _LISTENER_REFS.append(listener)

        if hasattr(frame, "addFocusListener"):
            frame.addFocusListener(listener)
        if hasattr(frame, "addFrameActionListener"):
            frame.addFrameActionListener(listener)
        if hasattr(frame, "addTopWindowListener"):
            frame.addTopWindowListener(listener)
        if hasattr(frame, "addWindowListener"):
            frame.addWindowListener(listener)
        if hasattr(ventana, "addFocusListener"):
            ventana.addFocusListener(listener)
        if hasattr(ventana, "addTopWindowListener"):
            ventana.addTopWindowListener(listener)
        if hasattr(ventana, "addWindowListener"):
            ventana.addWindowListener(listener)

        return True
    except Exception as exc:
        _registrar_error_foco("No se pudo registrar el seguimiento de foco de Calc", exc)
        return False


def enfocar_celda_sin_azul(documento, columna, fila):
    """
    Mueve el recuadro negro de enfoque a una celda sin dejar un bloque azul.
    columna: entero (0 para A, 1 para B, etc.)
    fila: entero (0 para fila 1, 1 para fila 2, etc.)
    """
    controlador = documento.getCurrentController()

    hoja_activa = controlador.ActiveSheet
    num_hoja = hoja_activa.RangeAddress.Sheet

    view_data = controlador.ViewData
    partes_vista = view_data.split(";")

    indice_datos_hoja = num_hoja + 3

    if indice_datos_hoja < len(partes_vista):
        datos_hoja = partes_vista[indice_datos_hoja]

        delimitador = "/" if "/" in datos_hoja else "+"
        sub_partes = datos_hoja.split(delimitador)

        sub_partes[0] = str(columna)
        sub_partes[1] = str(fila)

        partes_vista[indice_datos_hoja] = delimitador.join(sub_partes)

    nuevo_view_data = ";".join(partes_vista)
    controlador.restoreViewData(nuevo_view_data)


def enfocar_ventana_de_calc(documento):
    """
    Devuelve el foco de teclado a la ventana de Calc sin modificar la celda activa.
    """
    controlador = documento.getCurrentController()
    frame = controlador.getFrame()

    ventana = None
    if hasattr(frame, "getComponentWindow"):
        ventana = frame.getComponentWindow()
    if ventana is None and hasattr(frame, "getContainerWindow"):
        ventana = frame.getContainerWindow()

    if ventana is not None and hasattr(ventana, "setFocus"):
        ventana.setFocus()


def calc_esta_enfocado(documento, uno_context=None):
    """
    Devuelve True si la ventana de Calc del documento parece tener el foco.
    """
    print("Verificando si Calc está enfocado...")
    try:
        wnck_estado = _calc_esta_enfocado_con_wnck(documento)
        if wnck_estado is not None:
            return wnck_estado

        controlador = documento.getCurrentController()
        if controlador is None:
            return False

        frame = controlador.getFrame()
        if frame is None:
            return False

        ventana = None
        if hasattr(frame, "getComponentWindow"):
            ventana = frame.getComponentWindow()
        if ventana is None and hasattr(frame, "getContainerWindow"):
            ventana = frame.getContainerWindow()

        if ventana is not None and hasattr(ventana, "hasFocus"):
            try:
                estado_foco = ventana.hasFocus()
                if estado_foco is not None:
                    return bool(estado_foco)
            except Exception as exc:
                _registrar_error_foco("Falló la consulta hasFocus() de la ventana de Calc", exc)

        estado_foco = _obtener_estado_foco()
        if estado_foco is True:
            return True

        return False
    except Exception as e:
        _registrar_error_foco("Error al verificar el foco de Calc", e)
        return False


def _calc_esta_enfocado_con_wnck(documento):
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Wnck", "3.0")
        from gi.repository import Gtk, Wnck
    except Exception:
        return None

    try:
        Gtk.init([])
        screen = Wnck.Screen.get_default()
        if screen is None:
            return None

        screen.force_update()
        ventana_activa = None
        if hasattr(screen, "get_active_window"):
            ventana_activa = screen.get_active_window()
        if ventana_activa is None and hasattr(screen, "get_previously_active_window"):
            ventana_activa = screen.get_previously_active_window()

        if ventana_activa is None:
            return False

        titulo_activo = None
        if hasattr(ventana_activa, "get_name"):
            titulo_activo = ventana_activa.get_name()
        elif hasattr(ventana_activa, "get_class_instance_name"):
            titulo_activo = ventana_activa.get_class_instance_name()

        controlador = documento.getCurrentController()
        if controlador is None:
            return False

        frame = controlador.getFrame()
        if frame is None or not hasattr(frame, "getTitle"):
            return False

        titulo_calc = frame.getTitle()
        titulo_activo_norm = _normalizar_titulo_ventana(titulo_activo)
        titulo_calc_norm = _normalizar_titulo_ventana(titulo_calc)

        if not titulo_activo_norm or not titulo_calc_norm:
            return False

        if titulo_activo_norm == titulo_calc_norm:
            return True

        if titulo_calc_norm in titulo_activo_norm:
            return True

        if "libreoffice calc" in titulo_activo_norm and "calc" in titulo_calc_norm:
            return True

        return False
    except Exception as exc:
        _registrar_error_foco("Falló la consulta nativa con libwnck", exc)
        return None


def _normalizar_titulo_ventana(titulo):
    texto = str(titulo or "").strip().lower()
    texto = " ".join(texto.split())
    return texto

