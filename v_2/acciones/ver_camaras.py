import threading
import time

from acciones._contexto import usar_contexto

# Tope de tiempo del aviso "Abriendo cámaras…": normalmente se cierra ANTES de esto, apenas
# camera_viewer avisa que su ventana ya se mostró (ver _esperar_ventana más abajo) -- esto solo
# protege contra el caso raro de que ese aviso nunca llegue (p. ej. el proceso queda colgado
# arrancando Qt), para que el recuadro no se quede en pantalla para siempre.
TOPE_ESPERA_SEGUNDOS = 8.0
INTERVALO_SONDEO_SEGUNDOS = 0.15


@usar_contexto
def ejecutar(ctx):
    # camera_viewer (PySide6) corre en su propio interprete de Python (ver
    # camera_viewer/launcher.py), nunca en el embebido de LibreOffice: en
    # Linux ese Python viene integrado a la distro y es fragil instalarle
    # paquetes (PySide6, opencv, numpy...). El boton solo lanza el
    # subproceso y sigue de largo -- no espera a que la ventana se cierre,
    # asi que no bloquea el resto de los botones de Calc mientras esta abierta.
    from camera_viewer.launcher import launch_detached
    from camera_viewer.shared_paths import ready_marker_path
    from dialogs.aviso_cargando import mostrar_aviso_temporal
    from dialogs.aviso_error import mostrar_aviso_error

    # La ventana de camera_viewer tarda ~1 s en aparecer (arranca su propio interprete y Qt):
    # este aviso ocupa ese hueco para que el usuario no le dé varios clics de más pensando que
    # no pasó nada. Se cierra apenas la ventana de verdad se muestra (ver _esperar_ventana), no
    # tras un tiempo fijo -- si el lanzamiento falla, se cierra de inmediato en su lugar.
    aviso = mostrar_aviso_temporal(context, "Abriendo cámaras…", titulo="Cámaras", duracion_segundos=TOPE_ESPERA_SEGUNDOS)

    try:
        proceso = launch_detached(BASE_DIR)
    except FileNotFoundError as exc:
        aviso.cerrar()
        print(f"[ver_camaras] {exc}")
        mostrar_aviso_error(context, str(exc), titulo="No se pudo abrir cámaras")
        return

    print(f"[ver_camaras] camera_viewer lanzado (pid={proceso.pid}); su log queda en logs/camera_viewer/")
    _esperar_ventana(proceso, ready_marker_path(proceso.pid), aviso)


def _esperar_ventana(proceso, marcador, aviso) -> None:
    """En un hilo aparte (para no bloquear el resto de los botones de Calc mientras tanto):
    cierra el aviso apenas camera_viewer avisa que su ventana ya se mostró (el archivo que crea
    al arrancar, ver camera_viewer/__main__.py) o apenas el proceso termina solo (p. ej. truena
    al iniciar) -- lo que pase primero. Si ninguna de las dos cosas pasa a tiempo, el propio
    aviso ya se cierra con su tope de tiempo (ver TOPE_ESPERA_SEGUNDOS): esto nunca lo deja
    esperando para siempre."""

    def vigilar() -> None:
        while not aviso.cerrado:
            if marcador.exists():
                aviso.cerrar()
                return
            if proceso.poll() is not None:
                aviso.cerrar()
                return
            time.sleep(INTERVALO_SONDEO_SEGUNDOS)

    threading.Thread(target=vigilar, daemon=True).start()
