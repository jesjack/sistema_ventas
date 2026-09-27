"""nucleo.tablas.hoja_desactualizada: main.ods se puede abrir sin pasar por open_system.sh (el
único que lo prehornea) -- un acceso directo viejo, o "Abrir reciente" de LibreOffice, disparan
igual el macro que lanza main.py. Esto detecta que la hoja prehorneada quedó vieja comparándola
contra la última actividad real, en vez de fiarse para siempre de que el título ya diga "VENTAS
REALIZADAS" (2026-09-24: así se sirvieron horas de ventas atrasadas sin ningún aviso)."""

import os
import tempfile
import unittest
from datetime import datetime

from nucleo.tablas import hoja_desactualizada


class TestHojaDesactualizada(unittest.TestCase):
    def crear_archivo(self, hace_segundos):
        archivo = tempfile.NamedTemporaryFile(delete=False)
        archivo.close()
        momento = datetime.now().timestamp() - hace_segundos
        os.utime(archivo.name, (momento, momento))
        self.addCleanup(os.unlink, archivo.name)
        return archivo.name

    def test_sin_ventas_hoy_nunca_esta_desactualizada(self):
        archivo = self.crear_archivo(hace_segundos=999999)
        self.assertFalse(hoja_desactualizada(archivo, []))

    def test_archivo_mas_nuevo_que_la_ultima_venta_no_esta_desactualizado(self):
        archivo = self.crear_archivo(hace_segundos=5)
        filas = [("10:00:00", "blusa", 50, 1, 50)]
        self.assertFalse(hoja_desactualizada(archivo, filas, ahora=datetime.now()))

    def test_archivo_mas_viejo_que_la_ultima_venta_si_esta_desactualizado(self):
        archivo = self.crear_archivo(hace_segundos=7200)  # prehorneado hace 2 horas
        ahora = datetime.now()
        filas = [(ahora.strftime("%H:%M:%S"), "APERTURA DE CAJA", "", "", "")]  # venta de AHORA
        self.assertTrue(hoja_desactualizada(archivo, filas, ahora=ahora))

    def test_compara_contra_la_ultima_fila_no_la_primera(self):
        archivo = self.crear_archivo(hace_segundos=1800)  # prehorneado hace 30 min
        ahora = datetime.now()
        filas = [
            ("08:00:00", "APERTURA DE CAJA", "", "", ""),  # anterior al prehorneado: no importa
            (ahora.strftime("%H:%M:%S"), "APERTURA DE CAJA", "", "", ""),  # posterior: sí importa
        ]
        self.assertTrue(hoja_desactualizada(archivo, filas, ahora=ahora))

    def test_archivo_inaccesible_no_revienta_confia_en_el_titulo(self):
        self.assertFalse(hoja_desactualizada("/ruta/que/no/existe.ods", [("10:00:00", "x", 1, 1, 1)]))


if __name__ == "__main__":
    unittest.main()
