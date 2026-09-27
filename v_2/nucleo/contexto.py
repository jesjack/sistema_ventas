from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class Contexto:
    """Lo que necesitan los botones (acciones/) y el controlador de venta: la hoja, las tablas y los
    servicios ya construidos. Se pasa explícito a cada `ejecutar(ctx)`; antes era el `globals()` de
    main.py, sin que nada declarara de dónde salía cada nombre."""

    base_dir: Path
    context: Any  # contexto UNO
    desktop: Any
    documento: Any
    hoja: Any
    sheet_admin: Any
    table_manager: Any
    tabla_entrada: Any
    cart: Any
    ventas: Any  # tabla "VENTAS REALIZADAS"
    catalogo: Any  # CatalogoService
    codigos_barras: Any  # CodigosBarrasService
    autocompletado_handler: Any = None
    acciones: dict = field(default_factory=dict)  # nombre de archivo -> módulo de acciones/
    selling: bool = False  # hay un cobro en curso: Enter no debe iniciar otro

    # Compatibilidad con @usar_contexto (acciones/_contexto.py), que copia el contexto como globales del
    # módulo de la acción. Solo lo sigue usando acciones/ver_camaras.py (la app de cámaras la mantiene
    # otra instancia); las acciones nuevas usan `ctx.atributo`. Cuando ver_camaras deje de usarlo,
    # borrar esto y usar_contexto.
    def keys(self):
        return [f.name for f in fields(self)] + ["BASE_DIR"]

    def __getitem__(self, clave):
        return self.base_dir if clave == "BASE_DIR" else getattr(self, clave)
