// Medidas reales de una hoja de NexSheets, sin estimar: el ancho útil del área de la tabla (sin la
// columna de números de fila) y lo que ocupa todo lo que no es la tabla (barra de fórmulas,
// bordes). Se miden POR FUERA de la zona con scroll (offsetWidth/offsetHeight incluyen sus
// barras): si se midiera por dentro, una barra que aparece cambia la medida, el ajuste la vuelve a
// provocar y las barras se sostienen solas.
//
// Se vuelve a medir cuando cambia el contenedor, cuando cambia el área de la tabla (p. ej. aparece
// el carril vertical de NexSheets al pasar de las filas visibles: le quita 14 px) y cuando terminan
// de cargar las fuentes (los anchos de las columnas se calculan con ellas).

import { useEffect, useState, type DependencyList, type RefObject } from 'react'

export interface MarcoHoja {
  anchoUtil: number
  extraAlto: number
  /** Ancho de la columna de números de fila. */
  anchoRotulos: number
  /** Cambia cuando cargan fuentes: los anchos medidos con la fuente anterior ya no valen. */
  fuentes: number
}

export function useMarcoHoja(ref: RefObject<HTMLElement | null>, deps: DependencyList): MarcoHoja {
  const [marco, setMarco] = useState<MarcoHoja>({ anchoUtil: 0, extraAlto: 0, anchoRotulos: 0, fuentes: 0 })
  useEffect(() => {
    const nodo = ref.current
    if (!nodo) return
    const observador = new ResizeObserver(() => medir())
    let vistaObservada: HTMLElement | null = null
    const medir = () => {
      const editor = nodo.querySelector<HTMLElement>('.nx-sheets')
      // `.nx-sheet` contiene el área con scroll Y sus carriles: su tamaño no cambia cuando un carril
      // aparece o desaparece. Medir el área (que sí cambia) provocaba un ciclo: carril vertical →
      // menos ancho → carril horizontal → menos alto → otras filas visibles → sin carril vertical…
      const vista = nodo.querySelector<HTMLElement>('.nx-sheet')
      const esquina = nodo.querySelector<HTMLElement>('.nx-sheet__corner')
      if (!editor || !vista) return
      // La hoja puede montarse después (o volver a montarse): se observa su área en cuanto exista.
      if (vista !== vistaObservada) {
        if (vistaObservada) observador.unobserve(vistaObservada)
        observador.observe(vista)
        vistaObservada = vista
      }
      const anchoRotulos = esquina?.offsetWidth ?? 0
      // Un píxel de holgura: los anchos de las columnas se redondean y no deben sumar de más.
      const anchoUtil = vista.offsetWidth - (esquina?.offsetWidth ?? 0) - 1
      const extraAlto = editor.offsetHeight - vista.offsetHeight
      setMarco((m) =>
        m.anchoUtil === anchoUtil && m.extraAlto === extraAlto && m.anchoRotulos === anchoRotulos
          ? m
          : { ...m, anchoUtil, extraAlto, anchoRotulos },
      )
    }
    medir()
    observador.observe(nodo)
    const fuentesListas = () => {
      setMarco((m) => ({ ...m, fuentes: m.fuentes + 1 }))
      medir()
    }
    document.fonts.addEventListener('loadingdone', fuentesListas)
    void document.fonts.ready.then(fuentesListas)
    return () => {
      observador.disconnect()
      document.fonts.removeEventListener('loadingdone', fuentesListas)
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return marco
}

/** Alto que queda desde el borde superior del elemento hasta el fondo de la ventana. */
export function useAltoDisponible(ref: RefObject<HTMLElement | null>, margenInferior: number, deps: DependencyList): number {
  const [alto, setAlto] = useState(0)
  useEffect(() => {
    const medir = () => {
      const nodo = ref.current
      if (nodo) setAlto(Math.max(0, Math.floor(window.innerHeight - nodo.getBoundingClientRect().top - margenInferior)))
    }
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return alto
}
