from acciones._contexto import usar_contexto


@usar_contexto
def ejecutar(ctx):
    # camera_viewer (PySide6) corre en su propio interprete de Python (ver
    # camera_viewer/launcher.py), nunca en el embebido de LibreOffice: en
    # Linux ese Python viene integrado a la distro y es fragil instalarle
    # paquetes (PySide6, opencv, numpy...). El boton solo lanza el
    # subproceso y sigue de largo -- no espera a que la ventana se cierre,
    # asi que no bloquea el resto de los botones de Calc mientras esta abierta.
    from camera_viewer.launcher import launch_detached

    try:
        proceso = launch_detached(BASE_DIR)
        print(f"[ver_camaras] camera_viewer lanzado (pid={proceso.pid}); su log queda en logs/camera_viewer/")
    except FileNotFoundError as exc:
        print(f"[ver_camaras] {exc}")
