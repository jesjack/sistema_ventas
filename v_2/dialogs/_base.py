"""Piezas comunes de los diálogos UNO: el armado de controles (que en todos era la misma
receta copiada) y los listeners."""

import unohelper
from com.sun.star.awt import (  # pyright: ignore[reportMissingImports]
    XActionListener,
    XItemListener,
    XTextListener,
)

_MODELOS = {
    "etiqueta": "com.sun.star.awt.UnoControlFixedTextModel",
    "campo": "com.sun.star.awt.UnoControlEditModel",
    "boton": "com.sun.star.awt.UnoControlButtonModel",
    "lista": "com.sun.star.awt.UnoControlListBoxModel",
    "casilla": "com.sun.star.awt.UnoControlCheckBoxModel",
}

ACEPTAR = 1  # PushButtonType OK
CANCELAR = 2  # PushButtonType CANCEL


def crear_peer(smgr, uno_context, modelo):
    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", uno_context)
    dialog.setModel(modelo)
    toolkit = smgr.createInstanceWithContext("com.sun.star.awt.ExtToolkit", uno_context)
    dialog.createPeer(toolkit, None)
    return dialog


class ConstructorDialogo:
    """Arma un UnoControlDialogModel control por control y al final crea el diálogo con su peer.

        c = ConstructorDialogo(uno_context, "Título", 210, 94)
        c.etiqueta("lblInstruccion", 8, 8, 194, 12, "Ingrese el código.")
        c.campo("txtCodigo", 88, 26, 114, 14)
        c.aceptar_cancelar(68)
        dialog = c.crear()
    """

    def __init__(self, uno_context, titulo, ancho, alto, x=120, y=80):
        self.uno_context = uno_context
        self.smgr = uno_context.ServiceManager
        self.modelo = self.smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", uno_context)
        self.modelo.PositionX = x
        self.modelo.PositionY = y
        self.modelo.Width = ancho
        self.modelo.Height = alto
        self.modelo.Title = titulo

    def agregar(self, tipo, nombre, x, y, ancho, alto, **propiedades):
        modelo = self.modelo.createInstance(_MODELOS[tipo])
        modelo.Name = nombre
        modelo.PositionX = x
        modelo.PositionY = y
        modelo.Width = ancho
        modelo.Height = alto
        for propiedad, valor in propiedades.items():
            setattr(modelo, propiedad, valor)
        self.modelo.insertByName(nombre, modelo)
        return modelo

    def etiqueta(self, nombre, x, y, ancho, alto, texto, multilinea=False, **propiedades):
        if multilinea:
            propiedades["MultiLine"] = True
        return self.agregar("etiqueta", nombre, x, y, ancho, alto, Label=texto, **propiedades)

    def campo(self, nombre, x, y, ancho, alto, texto="", max_len=None, **propiedades):
        if max_len is not None:
            propiedades["MaxTextLen"] = max_len
        return self.agregar("campo", nombre, x, y, ancho, alto, Text=texto, **propiedades)

    def casilla(self, nombre, x, y, ancho, alto, texto="", marcada=False, **propiedades):
        propiedades.setdefault("TriState", False)
        return self.agregar("casilla", nombre, x, y, ancho, alto, Label=texto, State=1 if marcada else 0, **propiedades)

    def boton(self, nombre, x, y, ancho, alto, etiqueta, tipo=0, por_defecto=False):
        propiedades = {"Label": etiqueta, "PushButtonType": tipo}
        if por_defecto:
            propiedades["DefaultButton"] = True
        return self.agregar("boton", nombre, x, y, ancho, alto, **propiedades)

    def aceptar_cancelar(self, y, x_aceptar=96, x_cancelar=146, ancho=46, alto=14, etiqueta_aceptar="Aceptar"):
        self.boton("btnOk", x_aceptar, y, ancho, alto, etiqueta_aceptar, ACEPTAR, por_defecto=True)
        self.boton("btnCancel", x_cancelar, y, ancho, alto, "Cancelar", CANCELAR)

    def crear(self):
        """El diálogo listo para execute(); quien lo pide debe hacer dispose()."""
        return crear_peer(self.smgr, self.uno_context, self.modelo)


def mostrar_y_cerrar(dialog):
    try:
        return dialog.execute()
    finally:
        dialog.dispose()


class EscuchaAccion(unohelper.Base, XActionListener):
    """Llama a `al_hacer_clic()` cuando se pulsa el botón al que se conecte."""

    def __init__(self, al_hacer_clic):
        self._al_hacer_clic = al_hacer_clic

    def actionPerformed(self, _evento):
        self._al_hacer_clic()

    def disposing(self, _evento):
        pass


class EscuchaTexto(unohelper.Base, XTextListener):
    """Llama a `al_cambiar()` con cada cambio del texto de un campo, mientras se escribe."""

    def __init__(self, al_cambiar):
        self._al_cambiar = al_cambiar

    def textChanged(self, _evento):
        self._al_cambiar()

    def disposing(self, _evento):
        pass


class EscuchaCasilla(unohelper.Base, XItemListener):
    """Llama a `al_cambiar(marcada: bool)` cada vez que se marca o desmarca una casilla.

    Lee el estado con `evento.Source.getState()`, no con `evento.Selected` -- ese campo de
    ItemEvent no es el booleano "quedó marcada" para una casilla (se comprobó con clics reales:
    quedaba invertido/sin aplicar). getState() es la misma forma en que el resto del código ya
    lee casillas."""

    def __init__(self, al_cambiar):
        self._al_cambiar = al_cambiar

    def itemStateChanged(self, evento):
        self._al_cambiar(evento.Source.getState() == 1)

    def disposing(self, _evento):
        pass



# 2026-09-25: se intentó un EscuchaDobleClic con XMouseListener para abrir un menú con doble clic
# en el encabezado de un botón (ui/panel_admin.py). Comprobado con tres controles distintos
# (etiqueta, botón, campo de texto), en un LibreOffice headless real: XMouseListener no entrega
# NINGÚN evento, ni siquiera mouseEntered al simplemente pasar el mouse por encima -- mientras que
# XActionListener/XItemListener (botones, casillas) sí funcionan de forma confiable, probado varias
# veces el mismo día. No se sabe si es una limitación del modo headless o del toolkit en general;
# dado que no se pudo verificar, no se dejó como opción disponible aquí. Si hace falta detectar un
# clic sobre texto plano en el futuro, probar primero en una sesión gráfica real (no headless)
# antes de asumir que funciona, y considerar un botón de un solo clic como alternativa segura.
