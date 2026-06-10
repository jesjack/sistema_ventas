#!/usr/bin/env python3
"""Compatibilidad para abrir Ventas de ayer desde Python.

Este envoltorio delega en ventas_de_ayer.sh, que es la implementación activa.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(script_dir, "ventas.db")
    os.execv("/bin/bash", ["bash", os.path.join(script_dir, "ventas_de_ayer.sh"), db_path])


if __name__ == "__main__":
    main()