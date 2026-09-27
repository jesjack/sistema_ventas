"""De donde salen host/usuario/contraseña del DVR real -- ya NO quemados en el código (por poco
se suben a GitHub con el commit de respaldo del 2026-09-26, ver el bloqueo del push por
"Credential Leakage"). Variables de entorno primero (para overrides puntuales, p. ej. los
scripts run_camera_viewer_emulated.* que apuntan al emulador local), si no un archivo .env en la
raíz del proyecto (ver .env.example -- nunca versionado, cada instalación pone el suyo)."""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_KEYS = ("DVR_HOST", "DVR_USER", "DVR_PASSWORD")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parser mínimo de un .env (KEY=VALOR por línea, '#' comentarios, comillas opcionales) --
    sin depender de python-dotenv: no está en requirements.txt y son solo 3 variables."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def dvr_credentials(env_file: Path = ENV_FILE) -> tuple[str, str, str]:
    """(host, usuario, contraseña). Falla claro en vez de caer de vuelta a un valor real quemado
    en el código si no se encuentra ninguna de las dos fuentes."""
    from_file = _parse_env_file(env_file)
    values = {key: os.environ.get(key) or from_file.get(key) for key in _KEYS}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            f"Faltan {', '.join(missing)}: defínelas como variable de entorno o en {env_file} "
            f"(copia .env.example y pon los valores reales)."
        )
    return values["DVR_HOST"], values["DVR_USER"], values["DVR_PASSWORD"]
