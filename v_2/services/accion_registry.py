from __future__ import annotations

import importlib.util
from pathlib import Path


def cargar_acciones(base_dir):
    acciones_dir = Path(base_dir) / "acciones"
    registro = {}
    if not acciones_dir.is_dir():
        return registro

    for archivo in sorted(acciones_dir.glob("*.py")):
        if archivo.name.startswith("_"):
            continue

        nombre = archivo.stem
        spec = importlib.util.spec_from_file_location(f"acciones.{nombre}", archivo)
        modulo = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(modulo)
        except Exception as exc:
            print(f"[accion_registry] No se pudo cargar '{archivo.name}': {exc}")
            continue

        if not callable(getattr(modulo, "ejecutar", None)):
            print(f"[accion_registry] '{archivo.name}' no define ejecutar(ctx); se ignora.")
            continue

        registro[nombre] = modulo

    return registro
