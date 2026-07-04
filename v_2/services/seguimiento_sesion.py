from __future__ import annotations

import threading
import time


class SeguimientoSesionSistema:
    def __init__(self, ventas_service, intervalo_segundos=60):
        self.ventas_service = ventas_service
        self.intervalo_segundos = max(5, int(intervalo_segundos))
        self._detener = threading.Event()
        self._lock = threading.Lock()
        self._cerrado = False

        datos_usuario = self.ventas_service.obtener_datos_usuario_sistema()
        self.usuario_id = self.ventas_service.asegurar_usuario_sistema(datos_usuario)
        self.sesion_id = self.ventas_service.iniciar_sesion_sistema(self.usuario_id)
        self._hilo = threading.Thread(
            target=self._bucle_latido,
            name="SeguimientoSesionSistema",
            daemon=True,
        )
        self._hilo.start()

    def _bucle_latido(self):
        while not self._detener.wait(self.intervalo_segundos):
            try:
                self.ventas_service.registrar_latido_sesion(self.sesion_id)
            except Exception:
                pass

    def cerrar(self, exitosa=True):
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True

        self._detener.set()
        try:
            self.ventas_service.cerrar_sesion_sistema(self.sesion_id, exitosa=exitosa)
        except Exception:
            pass

        if self._hilo.is_alive():
            self._hilo.join(timeout=2)

    def latido_inmediato(self):
        try:
            self.ventas_service.registrar_latido_sesion(self.sesion_id)
        except Exception:
            pass
