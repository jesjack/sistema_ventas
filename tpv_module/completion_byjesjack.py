def es_numero_texto(valor):
    valor = valor.strip()
    if not valor:
        return False

    for caracter in valor:
        if caracter not in "0123456789.,":
            return False

    return True


def es_codigo_texto(valor):
    valor = valor.strip()
    if not valor or " " in valor:
        return False

    permitidos = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(caracter not in permitidos for caracter in valor):
        return False

    if any(caracter.isdigit() for caracter in valor):
        return True

    return valor.isupper() and len(valor) <= 8


def unir_partes(partes, inicio, fin):
    return " ".join(parte for parte in partes[inicio : fin + 1] if parte)


def parsear_linea_catalogo(linea):
    linea = linea.strip()
    if not linea:
        return None

    partes = linea.split()
    if not partes:
        return None

    nombre = linea
    precio = 0.0
    tiene_precio = False
    codigo = ""

    if len(partes) >= 2 and es_numero_texto(partes[-2]) and not es_numero_texto(partes[-1]):
        nombre = unir_partes(partes, 0, len(partes) - 3)
        precio = float(partes[-2].replace(",", "."))
        tiene_precio = precio > 0
        codigo = partes[-1]
    elif es_numero_texto(partes[-1]):
        nombre = unir_partes(partes, 0, len(partes) - 2)
        precio = float(partes[-1].replace(",", "."))
        tiene_precio = precio > 0
    elif len(partes) >= 2 and es_codigo_texto(partes[-1]):
        nombre = unir_partes(partes, 0, len(partes) - 2)
        codigo = partes[-1]

    if not nombre:
        nombre = linea

    return {
        "nombre": nombre,
        "precio": precio,
        "tiene_precio": tiene_precio,
        "codigo": codigo,
    }


def cargar_catalogo():
    """Carga el catálogo desde catalogo.txt"""
    import os

    # Obtener la ruta del directorio principal (sistema_ventas)
    ruta_catalogo = os.path.join(os.path.dirname(os.path.dirname(__file__)), "catalogo.txt")

    if not os.path.exists(ruta_catalogo):
        # Si no está ahí, intentar desde la carpeta actual
        ruta_catalogo = "catalogo.txt"

    productos = []

    try:
        with open(ruta_catalogo, "r", encoding="utf-8") as f:
            for linea in f:
                registro = parsear_linea_catalogo(linea)
                if registro and registro["nombre"]:
                    productos.append(registro["nombre"])
        return productos
    except FileNotFoundError:
        print(f"Error: No se encontró catalogo.txt en {ruta_catalogo}")
        return []

productos = cargar_catalogo()

PREPOSICIONES = {"a", "ante", "bajo", "cabe", "con", "contra", "de", "desde",
                 "durante", "en", "entre", "hacia", "hasta", "mediante", "para",
                 "por", "según", "sin", "so", "sobre", "tras", "versus", "vía"}

def quitar_preposiciones(productos):
    resultado = []
    for producto in productos:
        palabras = producto.split()
        filtradas = [p for p in palabras if p.lower() not in PREPOSICIONES]
        sin_prep = " ".join(filtradas)
        resultado.append([producto, sin_prep])
    return resultado

def buscar(matriz, letras):
    letras = letras.lower()
    resultado = []
    for fila in matriz:
        sin_prep = fila[1]  # columna sin preposiciones
        palabras = sin_prep.split()
        # cada letra del string debe coincidir con el inicio de la palabra en esa posición
        if len(letras) > len(palabras):
            continue
        if all(palabras[i].lower().startswith(letras[i]) for i in range(len(letras))):
            resultado.append(fila)
    return resultado

if __name__ == "__main__":
    # Ejemplo de uso:
    tabla = quitar_preposiciones(productos)
    # Ejemplos:
    # print(buscar(tabla, "p"))    # todos los que empiezan con P
    print(buscar(tabla, "pp"))   # Pantalón Palazo
    # print(buscar(tabla, "pm"))   # Pantalón Mezclilla (Cargo, Campana, Holgado, Skinny)