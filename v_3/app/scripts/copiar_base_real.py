"""Copia la base REAL de la v2 a datos/ventas_copia.db para el prototipo (solo en la PC de la caja).

Usa la API de respaldo de SQLite y abre la original en modo de solo lectura, así que es seguro
aunque la v2 esté escribiendo en ese momento. La copia está en .gitignore: tiene ventas reales y
el repositorio es público, NO se sube.

Uso:  python3 -I scripts/copiar_base_real.py [ruta de la base real]
Por defecto: ~/sistema_ventas/v_2/share/ventas.db
"""

import sqlite3
import sys
from pathlib import Path

ORIGEN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "sistema_ventas" / "v_2" / "share" / "ventas.db"
DESTINO = Path(__file__).resolve().parent.parent / "datos" / "ventas_copia.db"


def main() -> None:
    if not ORIGEN.exists():
        sys.exit(f"No existe {ORIGEN}. Fuera de la caja usa scripts/crear_base_demo.py.")
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    origen = sqlite3.connect(f"file:{ORIGEN}?mode=ro", uri=True)
    destino = sqlite3.connect(DESTINO)
    origen.backup(destino)
    destino.close()
    origen.close()
    print(f"Copiada {ORIGEN} → {DESTINO}")


if __name__ == "__main__":
    main()
