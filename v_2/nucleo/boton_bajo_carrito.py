"""El botón de limpiar carrito va pegado debajo del carrito, alineado a su borde derecho, y baja o
sube con él a la misma distancia conforme la tabla crece o se vacía.

La macro Basic (TPV_CrearBoton en libreofficeModules/Module1) apila todos los botones en una sola
columna a la derecha; aquí, ya creados, se saca ese de la columna, se recorren hacia arriba los que
quedaban debajo para no dejar hueco, y se mueve la figura con UNO cada vez que el carrito se redibuja
(Table.al_redibujar)."""

import traceback

# Lo que separa el borde de abajo del carrito del borde de arriba del botón, en 1/100 mm (lo mismo
# que TPV_BUTTON_GAP entre botones de la columna).
MARGEN_BAJO_TABLA = 250

# Mismo color que el encabezado y el TOTAL del carrito (si la tabla no tiene, este), con letra
# blanca en negritas: así se lee como parte de la tabla y no como un botón más de la columna.
COLOR_RESPALDO = 0x1CA9C9
COLOR_TEXTO = 0xFFFFFF
NEGRITAS = 150.0  # com.sun.star.awt.FontWeight.BOLD


def buscar_forma(hoja, nombre):
    draw_page = hoja.getDrawPage()
    for indice in range(draw_page.getCount()):
        forma = draw_page.getByIndex(indice)
        if getattr(forma, "Name", "") == nombre:
            return forma
    return None


def compactar_columna(hoja, prefijo, nombre_excluido):
    """Recorre hacia arriba los botones de la columna (los que empiezan con `prefijo`) que estaban
    debajo de `nombre_excluido`, ocupando los mismos lugares que ya tenían en orden."""
    draw_page = hoja.getDrawPage()
    formas = []
    for indice in range(draw_page.getCount()):
        forma = draw_page.getByIndex(indice)
        nombre = getattr(forma, "Name", "")
        if nombre.startswith(prefijo):
            formas.append(forma)

    formas.sort(key=lambda forma: forma.Position.Y)
    lugares = [forma.Position for forma in formas]
    restantes = [forma for forma in formas if forma.Name != nombre_excluido]
    for forma, lugar in zip(restantes, lugares):
        if forma.Position.Y != lugar.Y or forma.Position.X != lugar.X:
            forma.Position = lugar


def aplicar_estilo(forma, color_fondo):
    modelo = forma.getControl()
    modelo.BackgroundColor = int(color_fondo)
    modelo.TextColor = COLOR_TEXTO
    modelo.FontWeight = NEGRITAS


class BotonBajoCarrito:
    def __init__(self, hoja, carrito, nombre_forma, margen=MARGEN_BAJO_TABLA):
        self.hoja = hoja
        self.carrito = carrito
        self.nombre_forma = nombre_forma
        self.margen = margen

    def posicion_destino(self, ancho_boton):
        ultima_columna = self.carrito.x + len(self.carrito.columnas) - 1
        celda = self.hoja.getCellByPosition(ultima_columna, self.carrito.ultima_fila_y())
        derecha = celda.Position.X + celda.Size.Width
        abajo = celda.Position.Y + celda.Size.Height
        return derecha - ancho_boton, abajo + self.margen

    def dar_estilo(self):
        # La macro Basic vuelve a crear el botón (sin estilo) en cada construir(), así que esto se
        # repite cada vez; y como el estilo es solo cosmético, si falla el botón sigue sirviendo.
        try:
            forma = buscar_forma(self.hoja, self.nombre_forma)
            if forma is not None:
                aplicar_estilo(forma, self.carrito.header_color or COLOR_RESPALDO)
        except Exception:
            print(f"[boton_bajo_carrito] No se pudo dar estilo al botón: {traceback.format_exc()}")

    def acomodar(self):
        # Corre dentro de cada redibujo del carrito (Enter, cobrar, limpiar...): un fallo aquí solo
        # debe dejar el botón donde estaba, nunca tumbar la operación del carrito.
        try:
            forma = buscar_forma(self.hoja, self.nombre_forma)
            if forma is None:
                return
            x, y = self.posicion_destino(forma.Size.Width)
            actual = forma.Position
            if actual.X == x and actual.Y == y:
                return
            actual.X = x
            actual.Y = y
            forma.Position = actual
        except Exception:
            print(f"[boton_bajo_carrito] No se pudo acomodar el botón: {traceback.format_exc()}")
