// Prueba de NexSheets (P2): el carrito como hoja de SOLO LECTURA (como la tabla de la hoja de Calc
// en la v2) y VENTAS REALIZADAS como tabla de datos, más una gráfica de ventas por hora.
//
// La hoja del carrito se regenera cada vez que cambia el carrito. Mide exactamente lo que hay
// (sin filas ni columnas vacías: el proveedor usa extent={false}) y nombra sus columnas con
// `headers`. El id de la hoja es FIJO para no perder la celda seleccionada al regenerarla.

import { cellKey, createSheet, createWorkbook, type Sheet, type Workbook } from '@nexfluid/react/sheets'
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
 * Anchos de columna ajustados al contenido: cada columna mide lo que su encabezado o su valor más
 * ancho, y la columna `flexible` ocupa además el espacio que sobra (sin hueco a la derecha), pero
 * nunca menos que su valor más largo (no recorta nombres).
 */
export function anchosAjustados(
  encabezados: readonly string[],
  valores: readonly (readonly string[])[],
  flexible: number,
  disponible: number,
  medir: (texto: string, encabezado?: boolean) => number,
): Record<number, number> {
  const anchos = encabezados.map((e, c) =>
    Math.ceil(Math.max(medir(e, true) + RELLENO_CABEZA, ...(valores[c] ?? []).map((v) => medir(v) + RELLENO_CELDA))),
  )
  const resto = anchos.reduce((suma, a, c) => (c === flexible ? suma : suma + a), 0)
  anchos[flexible] = Math.max(anchos[flexible]!, Math.floor(disponible - resto))
  return Object.fromEntries(anchos.map((a, c) => [c, a]))
}

/** Anchos del carrito: Precio, C. y Subtotal a su contenido; Producto ocupa el resto. */
export function anchosCarrito(
  carrito: readonly FilaCarrito[],
  disponible: number,
  medir: (texto: string, encabezado?: boolean) => number,
): Record<number, number> {
  const valores = [
    carrito.map((f) => f.producto),
    carrito.map((f) => String(f.precio)),
    carrito.map((f) => String(f.cantidad)),
    carrito.map((f) => String(f.subtotal)),
  ]
  return anchosAjustados(ENCABEZADOS_CARRITO, valores, 0, disponible, medir)
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

export const ID_HOJA_VENTAS = 'ventas'
const ENCABEZADOS_VENTAS = ['Hora', 'Producto', 'Precio', 'C.', 'Subtotal']
/** Filas visibles de VENTAS REALIZADAS antes de desplazarse. */
export const FILAS_VISIBLES_VENTAS = 12

const texto = (v: number | null) => (v === null ? '' : String(v))

/**
 * VENTAS REALIZADAS como hoja de solo lectura, con las columnas de la hoja de la v2. Los eventos
 * (APERTURA DE CAJA…) no llevan precio, cantidad ni subtotal.
 */
export function libroDeVentas(lineas: readonly LineaVenta[], anchos?: Record<number, number>): Workbook {
  const celdas: Sheet['cells'] = {}
  lineas.forEach((l, fila) => {
    ;[l.hora.slice(0, 5), l.producto, texto(l.precio), texto(l.cantidad), texto(l.subtotal)].forEach((v, c) => {
      if (v !== '') celdas[cellKey(fila, c)] = { input: v }
    })
  })
  const hoja: Sheet = {
    ...createSheet('Ventas realizadas', { rows: Math.max(lineas.length, 1), columns: 5, cells: celdas, headers: ENCABEZADOS_VENTAS }, ID_HOJA_VENTAS),
    ...(anchos ? { columnWidths: anchos } : {}),
  }
  return createWorkbook([hoja])
}

/** Anchos de VENTAS REALIZADAS: todo a su contenido; Producto ocupa el resto. */
export function anchosVentas(
  lineas: readonly LineaVenta[],
  disponible: number,
  medir: (texto: string, encabezado?: boolean) => number,
): Record<number, number> {
  const valores = [
    lineas.map((l) => l.hora.slice(0, 5)),
    lineas.map((l) => l.producto),
    lineas.map((l) => texto(l.precio)),
    lineas.map((l) => texto(l.cantidad)),
    lineas.map((l) => texto(l.subtotal)),
  ]
  return anchosAjustados(ENCABEZADOS_VENTAS, valores, 1, disponible, medir)
}

/**
 * Alto de VENTAS REALIZADAS: sus filas, hasta las que caben en `disponible` (px, todo el alto que
 * puede ocupar la hoja); con más, se desplaza. Sin medida todavía, FILAS_VISIBLES_VENTAS.
 */
export function altoHojaVentas(lineas: readonly LineaVenta[], extra: number, disponible = 0): number {
  const caben = disponible > 0 ? Math.max(1, Math.floor((disponible - extra) / ALTO_FILA_HOJA) - 1) : FILAS_VISIBLES_VENTAS
  return (Math.min(Math.max(lineas.length, 1), caben) + 1) * ALTO_FILA_HOJA + extra
}
