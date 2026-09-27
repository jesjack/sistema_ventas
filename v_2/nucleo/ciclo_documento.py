"""Ciclo de vida del documento de Calc: encontrarlo, vigilar que siga abierto, decidir qué pasa
cuando desaparece y cerrar LibreOffice."""

import time

from nucleo.config import EXCEPCION_CIERRE_NORMAL, MAX_RELANZAMIENTOS_POR_FALLO, VENTANA_RELANZAMIENTOS_SEGUNDOS
from services.modo_sistema import (
    registrar_intento_relanzamiento_por_fallo,
    reiniciar_intentos_relanzamiento_por_fallo,
    solicitar_relanzamiento,
)


def obtener_documento_calc(desktop):
    componente = desktop.getCurrentComponent()
    if componente is not None:
        try:
            if hasattr(componente, "supportsService") and componente.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                return componente
            if hasattr(componente, "getSheets"):
                return componente
        except Exception:
            pass

    componentes = desktop.getComponents().createEnumeration()
    while componentes.hasMoreElements():
        componente = componentes.nextElement()
        try:
            if hasattr(componente, "supportsService") and componente.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                return componente
            if hasattr(componente, "getSheets"):
                return componente
        except Exception:
            continue

    return None


def vigilar_documento(documento):
    """Bloquea mientras el documento siga vivo; al dejar de responder
    (cerrado con X, Alt+F4, botones o el ciclo de cambio de modo) devuelve la
    excepción que lo delató."""
    try:
        while True:
            # Si el documento se cierra, acceder a una propiedad básica lanza
            # una excepción.
            _ = documento.Title
            # main.ods nunca persiste datos por sí mismo (es solo una
            # interfaz sobre ventas.db, re-horneada por prebake_ventas.py en
            # cada apertura) -- resetear esto aquí, una vez por segundo, evita
            # el prompt de "¿guardar cambios?" al cerrar sin importar el
            # motivo, sin necesitar un listener de modificación reactivo.
            documento.setModified(False)
            time.sleep(1)
    except Exception as exc:
        return exc


def fue_cierre_normal_del_documento(exc):
    """True si `exc` es como se ve el cierre normal del documento (ver
    EXCEPCION_CIERRE_NORMAL). Cualquier otra excepción (ej. DisposedException
    porque soffice se cayó) NO cuenta como cierre normal."""
    return type(exc).__name__.endswith(EXCEPCION_CIERRE_NORMAL)


def resolver_salida_del_documento(exc):
    """Decide qué pasa tras dejar de responder el documento. Devuelve True si
    fue un cierre normal.

    - Cierre normal: se limpia el contador de relanzamientos y se sigue con el
      cierre de siempre (open_system.sh/.bat terminan si no hay relanzar.flag).
    - Cualquier otra excepción: se pide relanzar con el mismo mecanismo del
      cambio de modo (relanzar.flag), hasta MAX_RELANZAMIENTOS_POR_FALLO veces
      seguidas; después se cierra sin relanzar, para no ciclar sin fin.
      El flag solo lo consume el launcher cuando soffice termina, y eso lo
      hace terminar_libreoffice() al final del flujo de cada modo.
    """
    if fue_cierre_normal_del_documento(exc):
        reiniciar_intentos_relanzamiento_por_fallo()
        return True

    if registrar_intento_relanzamiento_por_fallo(
        MAX_RELANZAMIENTOS_POR_FALLO, VENTANA_RELANZAMIENTOS_SEGUNDOS
    ):
        print("[relanzamiento] Salida inesperada del documento: se relanza el sistema.")
        solicitar_relanzamiento()
    else:
        print(
            f"[relanzamiento] Salida inesperada y ya se agotaron los "
            f"{MAX_RELANZAMIENTOS_POR_FALLO} relanzamientos permitidos: no se relanza."
        )
    return False


def terminar_libreoffice(desktop):
    # Cerrar el documento (X, o el ciclo de cambio de modo) no mata el proceso
    # de soffice -- LibreOffice deja un "quickstarter" corriendo en segundo
    # plano. open_system.bat/.sh esperan a que el PROCESO termine para decidir
    # si relanzar, así que hay que forzar el cierre completo de la aplicación
    # aquí, no solo del documento.
    try:
        desktop.terminate()
    except Exception:
        pass
