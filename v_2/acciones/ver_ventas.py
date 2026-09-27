from dialogs.seleccionar_fecha_ventas import solicitar_fecha_ventas
from services.modo_sistema import escribir_modo, solicitar_relanzamiento


def ejecutar(ctx):
    fecha = solicitar_fecha_ventas(ctx.context)
    if fecha is None:
        return

    escribir_modo("ventas_dia", fecha=fecha)
    solicitar_relanzamiento()
    print(f"Cambiando a modo ver-ventas-del-dia para la fecha {fecha}...")
    ctx.desktop.terminate()
