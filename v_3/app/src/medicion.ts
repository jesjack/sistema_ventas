// Mediciones de la fase 0: cuánto tarda la ventana en pintar después de una tecla y cuánto
// tarda una consulta a Rust. Se guardan en un arreglo y se leen cada medio segundo, así que
// medir no provoca renders extra.

export class Serie {
  private valores: number[] = []
  private limite: number

  constructor(limite = 200) {
    this.limite = limite
  }

  agregar(ms: number) {
    this.valores.push(ms)
    if (this.valores.length > this.limite) this.valores.shift()
  }

  limpiar() {
    this.valores = []
  }

  resumen(): Resumen | null {
    const n = this.valores.length
    if (n === 0) return null
    const orden = [...this.valores].sort((a, b) => a - b)
    const p = (q: number) => orden[Math.min(n - 1, Math.floor(q * n))]
    return { n, mediana: p(0.5), p95: p(0.95), max: orden[n - 1] }
  }
}

export interface Resumen {
  n: number
  mediana: number
  p95: number
  max: number
}

/** Tiempo desde la tecla hasta el siguiente cuadro pintado (dos requestAnimationFrame). */
export function medirTecla(evento: KeyboardEvent, serie: Serie) {
  const inicio = evento.timeStamp
  requestAnimationFrame(() => requestAnimationFrame(() => serie.agregar(performance.now() - inicio)))
}

export async function medirConsulta<T>(serie: Serie, consulta: () => Promise<T>): Promise<T> {
  const inicio = performance.now()
  try {
    return await consulta()
  } finally {
    serie.agregar(performance.now() - inicio)
  }
}
