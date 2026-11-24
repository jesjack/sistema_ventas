// Prueba de NexSheets (P2): el carrito como hoja de SOLO LECTURA (como la tabla de la hoja de Calc
// en la v2) y VENTAS REALIZADAS como tabla de datos, más una gráfica de ventas por hora.
//
// La hoja del carrito se regenera cada vez que cambia el carrito. Mide exactamente lo que hay
// (sin filas ni columnas vacías: el proveedor usa extent={false}) y nombra sus columnas con
// `headers`. El id de la hoja es FIJO para no perder la celda seleccionada al regenerarla.

import { cellKey, createSheet, createWorkbook, sheetFromRows, type Sheet, type Workbook } from '@nexfluid/react/sheets'
import type { FilaCarrito } from './carrito.ts'

export const ID_HOJA_CARRITO = 'carrito'
/** Alto de fila de NexSheets (`ROW_H` en su grid.tsx) y del encabezado. */
export const ALTO_FILA_HOJA = 30

const ENCABEZADOS_CARRITO = ['Producto', 'Precio', 'C.', 'Subtotal']

/**
 * Mide un texto con la tipografía real de NexSheets (la de `.nx-sheet__cell` o, para los
 * encabezados, la de `.nx-sheet__head-name`), leyendo sus tokens del documento.
 */
export function medidorDeTexto(raiz: HTMLElement): (texto: string, encabezado?: boolean) => number {
  // Los tamaños de NexFluid vienen en rem, y un <canvas> fuera de la página no los entiende (los
  // ignora y mide con su fuente de 10 px). Se resuelven con un elemento temporal dentro de `raiz`,
  // que hereda los tokens y devuelve la fuente ya en px.
  const resolver = (font: string) => {
    const span = document.createElement('span')
    span.style.cssText = `position:absolute;visibility:hidden;font:${font}`
    raiz.appendChild(span)
    const css = getComputedStyle(span)
    const resuelta = `${css.fontWeight} ${css.fontSize} ${css.fontFamily}`
    span.remove()
    return resuelta
  }
  const celda = resolver('450 var(--nx-text-small) var(--nx-font-body)')
  const cabeza = resolver('550 var(--nx-text-micro) var(--nx-font-body)')
  const ctx = document.createElement('canvas').getContext('2d')!
  return (texto, encabezado = false) => {
    ctx.font = encabezado ? cabeza : celda
    return ctx.measureText(texto).width
  }
}

// Relleno horizontal de NexSheets: celdas 8 px por lado, encabezados 6 px; +1 px de la línea y
// un margen para que nada quede justo al borde.
const RELLENO_CELDA = 16 + 1 + 6
const RELLENO_CABEZA = 12 + 1 + 6

/**
 * Anchos de las columnas del carrito ajustados al contenido: Precio, C. (cantidad) y Subtotal al
 * más ancho entre su encabezado y sus números; Producto ocupa el espacio que sobra (sin hueco a
 * la derecha) pero nunca menos que el nombre más largo.
 */
export function anchosCarrito(
  carrito: readonly FilaCarrito[],
  disponible: number,
  medir: (texto: string, encabezado?: boolean) => number,
): Record<number, number> {
  const columna = (indice: number, valores: string[]) =>
    Math.ceil(Math.max(medir(ENCABEZADOS_CARRITO[indice]!, true) + RELLENO_CABEZA, ...valores.map((v) => medir(v) + RELLENO_CELDA)))
  const precio = columna(1, carrito.map((f) => String(f.precio)))
  const cantidad = columna(2, carrito.map((f) => String(f.cantidad)))
  const subtotal = columna(3, carrito.map((f) => String(f.subtotal)))
  const nombreMasLargo = columna(0, carrito.map((f) => f.producto))
  const producto = Math.max(nombreMasLargo, Math.floor(disponible - precio - cantidad - subtotal))
  return { 0: producto, 1: precio, 2: cantidad, 3: subtotal }
}

/** Libro con una hoja: una fila por producto; el subtotal es una fórmula (`=Precio*Cantidad`). */
export function libroDeCarrito(carrito: readonly FilaCarrito[], anchos: Record<number, number> = { 0: 280 }): Workbook {
  const celdas: Sheet['cells'] = {}
  carrito.forEach((f, fila) => {
    const n = fila + 1 // en las fórmulas las filas se numeran desde 1
    celdas[cellKey(fila, 0)] = { input: f.producto }
    celdas[cellKey(fila, 1)] = { input: String(f.precio) }
    celdas[cellKey(fila, 2)] = { input: String(f.cantidad) }
    celdas[cellKey(fila, 3)] = { input: `=B${n}*C${n}` }
  })
  const hoja: Sheet = {
    ...createSheet(
      'Carrito',
      { rows: Math.max(carrito.length, 1), columns: 4, cells: celdas, headers: ENCABEZADOS_CARRITO },
      ID_HOJA_CARRITO,
    ),
    columnWidths: anchos,
  }
  return createWorkbook([hoja])
}

/**
 * Alto exacto de la hoja del carrito: encabezado + una fila por producto (al menos una), más
 * `extra`, lo que ocupa todo lo que no es la tabla (barra de fórmulas, bordes), MEDIDO en la página.
 */
export function altoHojaCarrito(carrito: readonly FilaCarrito[], extra: number): number {
  return (Math.max(carrito.length, 1) + 1) * ALTO_FILA_HOJA + extra
}

/**
 * Una fila de VENTAS REALIZADAS (núcleo: `nucleo::FilaVentas`): un producto vendido, un evento
 * (APERTURA DE CAJA, CORTE DE CAJA…: sin precio, cantidad ni subtotal) o, tras un corte, una pieza
 * del cambio que se dejó en la caja.
 */
export interface LineaVenta {
  hora: string
  producto: string
  precio: number | null
  cantidad: number | null
  subtotal: number | null
}

/** Tabla de lo vendido un día, con las mismas columnas que la hoja de la v2. */
export function hojaDeVentas(lineas: readonly LineaVenta[]): Sheet {
  const filas: (string | number)[][] = [['Hora', 'Producto', 'Precio', 'Cantidad', 'Subtotal']]
  for (const l of lineas) filas.push([l.hora.slice(0, 5), l.producto, l.precio ?? '', l.cantidad ?? '', l.subtotal ?? ''])
  return sheetFromRows('Ventas realizadas', filas)
}
