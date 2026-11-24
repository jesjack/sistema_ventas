// Depurador de la gota de NexFluid (solo para desarrollo).
//
// En cada cuadro busca todas las gotas visibles (`path.nx-liquid__drop`), mide el punto de su
// borde derecho a la altura de su centro y lo va dibujando en verde mientras la gota se mueve.
// Cada punto es un cuadro de animación: si los puntos quedan separados, la gota iba rápido ahí;
// si se amontonan, iba lenta. El rastro se queda hasta el siguiente movimiento.
//
// El rastro se dibuja DENTRO del mismo <svg> que la gota: comparte sus coordenadas, se desplaza
// con la lista y sube con ella a la capa superior (Popover API).

const SVG = 'http://www.w3.org/2000/svg'
const VERDE = '#16a34a'
/** Tras este tiempo quieta, el siguiente movimiento empieza un rastro nuevo. */
const PAUSA_MS = 500
const MAX_PUNTOS = 3000

interface Rastro {
  linea: SVGPathElement
  muestras: SVGPathElement
  actual: SVGCircleElement
  puntos: [number, number][]
  ultimo: [number, number] | null
  ultimoCambio: number
}

/** Borde derecho de la gota a la altura de su centro, en coordenadas del <svg> (búsqueda binaria). */
function bordeDerecho(gota: SVGPathElement): [number, number] | null {
  const svg = gota.ownerSVGElement
  if (!svg || !gota.getAttribute('d')) return null
  const caja = gota.getBBox()
  if (caja.width < 1 || caja.height < 1) return null
  const p = svg.createSVGPoint()
  p.y = caja.y + caja.height / 2
  let dentro = caja.x + caja.width / 2
  let fuera = caja.x + caja.width + 1
  p.x = dentro
  if (!gota.isPointInFill(p)) return null
  while (fuera - dentro > 0.05) {
    p.x = (dentro + fuera) / 2
    if (gota.isPointInFill(p)) dentro = p.x
    else fuera = p.x
  }
  return [dentro, p.y]
}

function crearRastro(gota: SVGPathElement): Rastro {
  const svg = gota.ownerSVGElement!
  const linea = document.createElementNS(SVG, 'path')
  linea.setAttribute('fill', 'none')
  linea.setAttribute('stroke', VERDE)
  linea.setAttribute('stroke-width', '1.5')
  linea.setAttribute('stroke-linejoin', 'round')
  const muestras = document.createElementNS(SVG, 'path')
  muestras.setAttribute('fill', 'none')
  muestras.setAttribute('stroke', VERDE)
  muestras.setAttribute('stroke-width', '3.5')
  muestras.setAttribute('stroke-linecap', 'round')
  const actual = document.createElementNS(SVG, 'circle')
  actual.setAttribute('r', '3')
  actual.setAttribute('fill', VERDE)
  for (const el of [linea, muestras, actual]) {
    el.classList.add('depurar-gota')
    svg.append(el)
  }
  return { linea, muestras, actual, puntos: [], ultimo: null, ultimoCambio: 0 }
}

function pintar(r: Rastro) {
  const f = (n: number) => n.toFixed(2)
  r.linea.setAttribute('d', r.puntos.map(([x, y], i) => `${i ? 'L' : 'M'}${f(x)} ${f(y)}`).join(''))
  // Un punto por cuadro: un segmento de longitud cero con extremo redondo se ve como punto.
  r.muestras.setAttribute('d', r.puntos.map(([x, y]) => `M${f(x)} ${f(y)}h0`).join(''))
  const ultimo = r.puntos[r.puntos.length - 1]
  if (ultimo) {
    r.actual.setAttribute('cx', f(ultimo[0]))
    r.actual.setAttribute('cy', f(ultimo[1]))
  }
}

/** Empieza a depurar todas las gotas de la página. Devuelve la función que lo detiene y limpia. */
export function iniciarDepuracionGota(): () => void {
  const rastros = new Map<SVGPathElement, Rastro>()
  let cuadro = 0

  const paso = (ahora: number) => {
    for (const [gota, r] of rastros) {
      if (!gota.isConnected) {
        for (const el of [r.linea, r.muestras, r.actual]) el.remove()
        rastros.delete(gota)
      }
    }
    for (const gota of document.querySelectorAll<SVGPathElement>('path.nx-liquid__drop')) {
      const punto = bordeDerecho(gota)
      if (!punto) continue
      let r = rastros.get(gota)
      if (!r) {
        r = crearRastro(gota)
        rastros.set(gota, r)
      }
      const quieta = r.ultimo && Math.hypot(punto[0] - r.ultimo[0], punto[1] - r.ultimo[1]) < 0.05
      if (!quieta) {
        if (ahora - r.ultimoCambio > PAUSA_MS) r.puntos = r.ultimo ? [r.ultimo] : []
        r.puntos.push(punto)
        if (r.puntos.length > MAX_PUNTOS) r.puntos.shift()
        r.ultimoCambio = ahora
        pintar(r)
      }
      r.ultimo = punto
    }
    cuadro = requestAnimationFrame(paso)
  }
  cuadro = requestAnimationFrame(paso)

  return () => {
    cancelAnimationFrame(cuadro)
    for (const r of rastros.values()) for (const el of [r.linea, r.muestras, r.actual]) el.remove()
    rastros.clear()
  }
}
