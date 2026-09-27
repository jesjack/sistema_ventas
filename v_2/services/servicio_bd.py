from __future__ import annotations

from services.base_datos import conectar, ruta_db
from services.esquema import asegurar_esquema


class ServicioBD:
    """Base de los servicios que leen/escriben ventas.db: resuelve la ruta,
    garantiza que el esquema exista y abre conexiones con las claves foraneas
    activas."""

    def __init__(self, db_path=None):
        self.db_path = ruta_db(db_path)
        asegurar_esquema(self.db_path)

    def _connect(self):
        return conectar(self.db_path)
