"""Reglas del carrito, sin hoja, base de datos ni ventanas: operan sobre cualquier
objeto con la interfaz de lista de `Table` (indexar, append, clear...)."""


def agregar_al_carrito(tabla_entrada, carrito):
    """Pasa la fila de "INGRESE LOS DATOS" al carrito (sumando cantidades si el
    producto y el precio ya estaban) y deja la entrada lista para el siguiente.
    Devuelve False si faltaba algun dato y no se agrego nada."""
    datos = list(tabla_entrada[0])
    if not datos:
        return False

    producto, precio, cantidad = datos
    if not producto or not precio or not cantidad:
        print("Todos los campos deben estar completos para agregar al carrito.")
        return False

    for indice, fila in enumerate(carrito):
        if fila[0] == producto and fila[1] == precio:
            cantidad_total = fila[2] + cantidad
            carrito[indice] = (producto, precio, cantidad_total, precio * cantidad_total)
            break
    else:
        carrito.append((producto, precio, cantidad, precio * cantidad))

    tabla_entrada.clear()
    tabla_entrada.append(["", "", 1])
    return True


def total_del_carrito(carrito):
    return sum(float(fila[3]) for fila in carrito)
