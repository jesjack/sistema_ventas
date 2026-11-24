// Medidas reales de una hoja de NexSheets, sin estimar: el ancho útil del área de la tabla (sin la
// columna de números de fila) y lo que ocupa todo lo que no es la tabla (barra de fórmulas,
// bordes). Se miden POR FUERA de la zona con scroll (offsetWidth/offsetHeight incluyen sus
// barras): si se midiera por dentro, una barra que aparece cambia la medida, el ajuste la vuelve a
// provocar y las barras se sostienen solas.

import { useEffect, useState, type DependencyList, type RefObject } from 'react'

export interface MarcoHoja {
  anchoUtil: number
  extraAlto: number
}

export function useMarcoHoja(ref: RefObject<HTMLElement | null>, deps: DependencyList): MarcoHoja {
  const [marco, setMarco] = useState<MarcoHoja>({ anchoUtil: 0, extraAlto: 0 })
  useEffect(() => {
    const nodo = ref.current
    if (!nodo) return
    const medir = () => {
      const editor = nodo.querySelector<HTMLElement>('.nx-sheets')
      const vista = nodo.querySelector<HTMLElement>('.nx-sheet__viewport')
      const esquina = nodo.querySelector<HTMLElement>('.nx-sheet__corner')
      if (!editor || !vista) return
      const anchoUtil = vista.offsetWidth - (esquina?.offsetWidth ?? 0)
      const extraAlto = editor.offsetHeight - vista.offsetHeight
      setMarco((m) => (m.anchoUtil === anchoUtil && m.extraAlto === extraAlto ? m : { anchoUtil, extraAlto }))
    }
    medir()
    const observador = new ResizeObserver(medir)
    observador.observe(nodo)
    return () => observador.disconnect()
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return marco
}
