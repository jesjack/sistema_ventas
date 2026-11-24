// Reglas del carrito, iguales a las de v_2/table_modules/carrito.py:
// si el producto y el precio ya están, se suman las cantidades; si no, se agrega una fila.

export interface FilaCarrito {
  producto: string
  precio: number
  cantidad: number
  subtotal: number
}

export function agregarAlCarrito(
  carrito: readonly FilaCarrito[],
  producto: string,
  precio: number,
  cantidad: number,
): FilaCarrito[] | null {
  if (!producto || !precio || !cantidad) return null
  const indice = carrito.findIndex((f) => f.producto === producto && f.precio === precio)
  if (indice === -1) {
    return [...carrito, { producto, precio, cantidad, subtotal: precio * cantidad }]
  }
  return carrito.map((f, i) => {
    if (i !== indice) return f
    const total = f.cantidad + cantidad
    return { ...f, cantidad: total, subtotal: f.precio * total }
  })
}

export function totalDelCarrito(carrito: readonly FilaCarrito[]): number {
  return carrito.reduce((suma, f) => suma + f.subtotal, 0)
}

const formato = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' })
export const dinero = (n: number) => formato.format(n)

/** Lee "12", "12.5" o "12,50" como número; devuelve NaN si no es un número. */
export function leerNumero(texto: string): number {
  const limpio = texto.trim().replace(',', '.').replace(/^\$/, '')
  return limpio === '' ? NaN : Number(limpio)
}
