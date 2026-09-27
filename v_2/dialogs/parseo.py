"""Lectura de lo que el usuario escribe en los diálogos (sin UNO, para poder probarla)."""


def parse_monto(texto):
    """"1,234.50", "1.234,50", "12,5" o "12.5" -> float. ValueError si esta vacio o no es un numero.
    Devuelve None si `texto` es None."""
    if texto is None:
        return None

    limpio = str(texto).strip().replace(" ", "")
    if not limpio:
        raise ValueError("monto vacio")

    if "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")

    return float(limpio)


def parse_copias(texto):
    if texto is None:
        raise ValueError("copias vacias")

    limpio = str(texto).strip()
    if not limpio:
        raise ValueError("copias vacias")

    return int(limpio)
