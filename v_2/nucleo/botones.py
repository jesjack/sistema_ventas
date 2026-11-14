"""Los botones de la hoja: se arman con los que el usuario tiene visibles en la base de datos y cada
uno ejecuta su archivo de acciones/."""

from nucleo.boton_bajo_carrito import BotonBajoCarrito, compactar_columna
from nucleo.config import ADMIN_RAIZ

# Igual que TPV_BUTTON_PREFIX en libreofficeModules/Module1: la figura de cada botón en la hoja se
# llama así + su action_id.
PREFIJO_FORMA = "tpv_action_"

# Este botón no va en la columna de la derecha sino pegado debajo del carrito (ver
# nucleo/boton_bajo_carrito.py).
ACCION_BAJO_CARRITO = "limpiar_carrito"


class BotonesDeLaHoja:
    def __init__(self, ctx, bridge, botones_service, usuario_id, usuario_actual):
        self.ctx = ctx
        self.bridge = bridge
        self.botones_service = botones_service
        self.usuario_id = usuario_id
        self.usuario_actual = usuario_actual
        self._ultimo_resumen = None

    def construir(self):
        # Se puede volver a llamar (ej. al detectar un cambio hecho desde
        # admin_botones, ver revisar_cambios) para reflejar cambios de
        # botones/visibilidad sin reiniciar el sistema: reset_buttons()
        # limpia el estado en memoria y publish_layout() manda a Basic a
        # borrar y recrear los controles en la hoja con la lista actualizada.
        self.bridge.reset_buttons()

        # Se registra primero para que quede arriba del todo
        # (SheetButtonBridge apila los botones en el mismo orden en que
        # se registran).
        if self.usuario_actual == ADMIN_RAIZ:
            self.bridge.add_button("ADMINISTRAR ADMINS", self.abrir_panel_admin)

        nombre_forma_bajo_carrito = None
        botones_visibles = []
        if self.usuario_id is not None:
            botones_visibles = self.botones_service.listar_botones_visibles_para(self.usuario_id)

        for boton_id, etiqueta, archivo_accion, _orden in botones_visibles:
            modulo = self.ctx.acciones.get(archivo_accion)
            if modulo is None:
                print(f"[botones] '{etiqueta}' referencia '{archivo_accion}', que no existe en acciones/. Se omite.")
                continue

            # SheetButtonBridge identifica cada boton por handler.__name__,
            # y todas las lambdas comparten el mismo __name__
            # ("<lambda>") -- sin esto, todos los botones dinamicos
            # colisionan en un solo action_id y se pisan entre si en la hoja.
            def manejador(modulo=modulo):
                return modulo.ejecutar(self.ctx)

            manejador.__name__ = f"boton_dinamico_{boton_id}"
            if archivo_accion == ACCION_BAJO_CARRITO:
                nombre_forma_bajo_carrito = PREFIJO_FORMA + manejador.__name__

            self.bridge.add_button(etiqueta, manejador)

        self.bridge.publish_layout()
        self._colocar_bajo_carrito(nombre_forma_bajo_carrito)

        # Punto de referencia para revisar_cambios(): cualquier cambio hecho DESPUES de este
        # construir() (por admin_botones, en su propio proceso) hará que el resumen difiera.
        self._ultimo_resumen = self.botones_service.resumen_cambios()

    def _colocar_bajo_carrito(self, nombre_forma):
        carrito = self.ctx.cart
        if nombre_forma is None:
            carrito.al_redibujar = None
            return

        boton = BotonBajoCarrito(self.ctx.hoja, carrito, nombre_forma)
        try:
            compactar_columna(self.ctx.hoja, PREFIJO_FORMA, nombre_forma)
        except Exception as exc:
            print(f"[botones] No se pudo recorrer la columna de botones: {exc}")
        boton.dar_estilo()
        boton.acomodar()
        carrito.al_redibujar = boton.acomodar

    def revisar_cambios(self):
        """Engancha aqui, via SheetButtonBridge.on_tick (ver nucleo/arranque.py), para notar
        cambios hechos desde admin_botones -- que corre en OTRO proceso, asi que no hay forma de
        que nos avise directo. Se apoya en el hilo de sondeo que YA existe (cada poll_interval,
        hoy 0.5s) en vez de levantar un hilo nuevo solo para esto."""
        resumen = self.botones_service.resumen_cambios()
        if resumen != self._ultimo_resumen:
            self.construir()

    def abrir_panel_admin(self):
        # Proceso aparte (Qt/PySide6, no un dialogo UNO bloqueante -- ver admin_botones/, que
        # reemplaza al extinto ui/panel_admin.py): no se espera a que cierre, asi que no se llama
        # a construir() aqui; revisar_cambios() se encarga de refrescar la hoja sola cuando la
        # ventana guarde algo.
        from admin_botones.launcher import launch_detached

        try:
            proceso = launch_detached(self.ctx.base_dir)
        except FileNotFoundError as exc:
            print(f"[admin_botones] {exc}")
            return

        if proceso is None:
            print("[admin_botones] Ya había una ventana abierta; se trajo al frente.")
            return
        print(f"[admin_botones] Ventana lanzada (pid={proceso.pid}); su log queda en logs/admin_botones/")
