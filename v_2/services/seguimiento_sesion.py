from __future__ import annotations

import os
import threading
import time


class SeguimientoSesionSistema:
    def __init__(self, usuarios_service, usuario_id, intervalo_segundos=60):
        # usuario_id ya viene resuelto por el llamador (via
        # usuarios_service.asegurar_usuario_sistema): la visibilidad de
        # botones necesita ese id incluso si este seguimiento de sesion
        # falla al construirse, asi que no se deriva aqui adentro.
        self.usuarios_service = usuarios_service
        self.usuario_id = usuario_id
        self.intervalo_segundos = max(5, int(intervalo_segundos))
        self._detener = threading.Event()
        self._lock = threading.Lock()
        self._cerrado = False

        self.sesion_id = self.usuarios_service.iniciar_sesion_sistema(
            self.usuario_id,
            pid=os.getpid(),
        )
        self._hilo = threading.Thread(
            target=self._bucle_latido,
            name="SeguimientoSesionSistema",
            daemon=True,
        )
        self._hilo.start()

    def _bucle_latido(self):
        while not self._detener.wait(self.intervalo_segundos):
            try:
                self.usuarios_service.registrar_latido_sesion(self.sesion_id)
            except Exception:
                pass

    def cerrar(self, exitosa=False, detalle=None):
        # exitosa=True solo debe pasarlo quien SABE que fue un cierre normal
        # (ver main.py); por defecto una salida no explicada cuenta como no
        # exitosa. "detalle" queda como motivo de salida en la sesión.
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True

        self._detener.set()
        try:
            self.usuarios_service.cerrar_sesion_sistema(
                self.sesion_id,
                detalle=detalle,
                exitosa=exitosa,
            )
        except Exception:
            pass

        if self._hilo.is_alive():
            self._hilo.join(timeout=2)

    def latido_inmediato(self):
        try:
            self.usuarios_service.registrar_latido_sesion(self.sesion_id)
        except Exception:
            pass
