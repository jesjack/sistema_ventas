import sys
from time import sleep as wait
import uno


def es_libreoffice_calc_enfocado(ctx) -> bool:
    """Verifica si el usuario está enfocado físicamente en la ventana activa

    de LibreOffice Calc.

    :param ctx: El contexto de componentes remotos de UNO (Component Context).
    :return: True si Calc tiene el foco real en pantalla, False en caso
    contrario.
    """
    try:
        # 1. Acceder al Administrador de Servicios desde el contexto recibido
        smgr = ctx.ServiceManager

        # 2. Obtener el servicio Desktop
        desktop = smgr.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx
        )

        # 3. Obtener el marco (Frame) activo en el ecosistema de LibreOffice
        frame_activo = desktop.getActiveFrame()

        if not frame_activo:
            return False

        # 4. Validar que el documento activo sea de tipo Calc (y no Writer o Impress)
        # Esto lo hacemos revisando si el componente soporta el servicio de hojas de cálculo
        modelo = frame_activo.getController().getModel()
        if not modelo or not modelo.supportsService(
            "com.sun.star.sheet.SpreadsheetDocument"
        ):
            return False

        # 5. Obtener el contenedor de la ventana física para revisar el foco del S.O.
        ventana_componente = frame_activo.getContainerWindow()

        # 6. .isActive() devuelve True únicamente si la ventana está al frente del usuario
        return bool(ventana_componente.isActive())

    except Exception:
        # Si ocurre un error de comunicación o la ventana se cerró abruptamente
        return True
