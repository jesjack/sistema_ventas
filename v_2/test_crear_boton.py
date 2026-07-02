import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import main


class MockButton:
    def __init__(self, name):
        self.name = name
        self.listener = None

    def addActionListener(self, listener):
        self.listener = listener
        print(f"{self.name}: listener tiene getTypes:", hasattr(listener, "getTypes"))
        print(f"{self.name}: tipos UNO:", listener.getTypes())


class MockDialog:
    def __init__(self):
        self.buttons = {}
        self.visible = False

    def setModel(self, model):
        self.model = model

    def createPeer(self, toolkit, parent):
        self.toolkit = toolkit

    def getControl(self, name):
        if name not in self.buttons:
            self.buttons[name] = MockButton(name)
        return self.buttons[name]

    def setVisible(self, visible):
        self.visible = visible


class MockModel:
    def __init__(self):
        self.props = {}

    def createInstance(self, service_name):
        return MockModel()

    def insertByName(self, name, value):
        self.props[name] = value

    def __setattr__(self, name, value):
        if name in {"props"}:
            object.__setattr__(self, name, value)
        else:
            self.props[name] = value


class MockServiceManager:
    def __init__(self):
        self.dialog = MockDialog()

    def createInstanceWithContext(self, service_name, context):
        if service_name == "com.sun.star.awt.UnoControlDialogModel":
            return MockModel()
        if service_name == "com.sun.star.awt.UnoControlDialog":
            return self.dialog
        if service_name == "com.sun.star.awt.ExtToolkit":
            return object()
        raise ValueError(service_name)


class MockContext:
    def __init__(self):
        self.ServiceManager = MockServiceManager()


def probar_crear_boton():
    contexto = MockContext()
    ventana = main.crear_ventana_acciones(contexto, titulo="Prueba de boton", x=20, y=20, ancho=120, alto=20)

    ventana.agregar_boton("PRUEBA", lambda: print("accion 1"))
    ventana.agregar_boton("PRUEBA MAS LARGA", lambda: print("accion 2"))
    dialog = ventana.mostrar()

    print("dialogo creado:", dialog is not None)
    print("mismo dialogo para ambos botones:", len(dialog.buttons) == 2)
    print("visible:", dialog.visible)
    print("botones en vertical:", dialog.model.props["btnAccion1"].props["PositionY"] < dialog.model.props["btnAccion2"].props["PositionY"])
    print("mismo ancho:", dialog.model.props["btnAccion1"].props["Width"] == dialog.model.props["btnAccion2"].props["Width"])
    print("padding simetrico:", dialog.model.props["btnAccion1"].props["PositionX"] == dialog.model.props["btnAccion2"].props["PositionX"])
    print("ancho crecio con el texto:", dialog.model.props["Width"] > dialog.model.props["btnAccion1"].props["Width"])
    print("alto crecio con mas botones:", dialog.model.props["Height"] > 20)
    return dialog


if __name__ == "__main__":
    probar_crear_boton()
