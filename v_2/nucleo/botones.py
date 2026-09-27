"""Los botones de la hoja: se arman con los que el usuario tiene visibles en la base de datos y cada
uno ejecuta su archivo de acciones/."""

from nucleo.config import ADMIN_RAIZ


class BotonesDeLaHoja:
    def __init__(self, ctx, bridge, botones_service, usuario_id, usuario_actual):
        self.ctx = ctx
        self.bridge = bridge
        self.botones_service = botones_service
        self.usuario_id = usuario_id
        self.usuario_actual = usuario_actual

    def construir(self):
        # Se puede volver a llamar (ej. al cerrar el panel de admin) para
        # reflejar cambios de botones/visibilidad sin reiniciar el
        # sistema: reset_buttons() limpia el estado en memoria y
        # publish_layout() manda a Basic a borrar y recrear los controles
        # en la hoja con la lista actualizada.
        self.bridge.reset_buttons()

        # Se registra primero para que quede arriba del todo
        # (SheetButtonBridge apila los botones en el mismo orden en que
        # se registran).
        if self.usuario_actual == ADMIN_RAIZ:
            self.bridge.add_button("ADMINISTRAR ADMINS", self.abrir_panel_admin)

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

            self.bridge.add_button(etiqueta, manejador)

        self.bridge.publish_layout()

    def abrir_panel_admin(self):
        from ui.panel_admin import abrir_panel_administracion

        abrir_panel_administracion(self.ctx.context, self.botones_service, self.usuario_actual)
        self.construir()
