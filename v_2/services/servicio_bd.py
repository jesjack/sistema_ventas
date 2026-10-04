from __future__ import annotations

from datetime import datetime

from services.base_datos import conectar, ruta_db
from services.esquema import asegurar_esquema


def ahora_local():
    """Fecha y hora local en el formato de la base ("2026-10-03 18:24:44")."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ServicioBD:
    """Base de los servicios que leen/escriben ventas.db: resuelve la ruta,
    garantiza que el esquema exista y abre conexiones con las claves foraneas
    activas.

    `sesion_id` es la sesion de sesiones_sistema de este proceso del POS: lo que
    el servicio registre queda firmado con ella (usuario y equipo salen de ahi).
    None fuera del POS (prehorneado, pruebas) o si la sesion no se pudo abrir."""

    def __init__(self, db_path=None, sesion_id=None):
        self.db_path = ruta_db(db_path)
        self.sesion_id = sesion_id
        asegurar_esquema(self.db_path)

    def _connect(self):
        return conectar(self.db_path)
