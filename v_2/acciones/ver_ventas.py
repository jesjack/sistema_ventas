from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    fecha = solicitar_fecha_ventas(context)
    if fecha is None:
        return

    escribir_modo("ventas_dia", fecha=fecha)
    solicitar_relanzamiento()
    print(f"Cambiando a modo ver-ventas-del-dia para la fecha {fecha}...")
    desktop.terminate()
