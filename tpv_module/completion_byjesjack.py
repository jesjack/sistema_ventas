def cargar_catalogo():
    """Carga el catálogo desde catalogo.txt"""
    import os
    # Obtener la ruta del directorio principal (sistema_ventas)
    ruta_catalogo = os.path.join(os.path.dirname(os.path.dirname(__file__)), "catalogo.txt")
    
    if not os.path.exists(ruta_catalogo):
        # Si no está ahí, intentar desde la carpeta actual
        ruta_catalogo = "catalogo.txt"
    
    try:
        with open(ruta_catalogo, "r", encoding="utf-8") as f:
            productos = [linea.strip() for linea in f if linea.strip()]
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