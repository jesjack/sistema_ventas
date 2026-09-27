"""Constantes del arranque y de las reglas del punto de venta."""

ADMIN_RAIZ = "jesjack"  # ve el botón "ADMINISTRAR ADMINS"
PUERTO_LIBREOFFICE = 2002
DEBUG_RUNS_TO_KEEP = 200  # ejecuciones que se conservan en logs/debug/; una tarde con
# muchas aperturas/cierres agota 20 en pocos dias (ver NOTAS del 2026-09-23: se perdio
# evidencia real de un fallo mientras se investigaba otro). Cada log pesa pocos KB.

# Salida inesperada del documento: cuántos relanzamientos seguidos se permiten
# y cuánto tiempo estable (desde el último intento) los reinicia.
MAX_RELANZAMIENTOS_POR_FALLO = 2
VENTANA_RELANZAMIENTOS_SEGUNDOS = 600

# Así se ve el cierre normal del documento (X, Alt+F4, botones, cambio de
# modo): documento.Title lanza esta excepción, "cannot get value Title".
# Observado en el 100 % de las salidas de logs/debug (18 de 18 hasta el
# 2026-09-19, incluida una provocada a propósito ese día).
EXCEPCION_CIERRE_NORMAL = "UnknownPropertyException"

# Código que autoriza abrir la caja desde el cobro cuando el carrito está vacío.
CODIGO_APERTURA_CAJA = "7410"
