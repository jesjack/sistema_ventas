// Distingue el escáner del tecleo por el ritmo, como v_2 (scanner_detector), pero dentro de la
// ventana: sin hook global ni root. El escáner "teclea" el código muy rápido y termina con Enter.

export interface Escaneo {
  codigo: string
  /** Promedio de milisegundos entre teclas del escaneo. */
  ritmoMs: number
}

export interface OpcionesEscaner {
  /** Pausa máxima entre teclas de un mismo escaneo. */
  maxPausaMs: number
  /** Largo mínimo de un código. */
  minCaracteres: number
}

const MODIFICADORAS = new Set(['Shift', 'Control', 'Alt', 'AltGraph', 'Meta', 'CapsLock'])

export const OPCIONES_ESCANER: OpcionesEscaner = { maxPausaMs: 35, minCaracteres: 4 }

export class DetectorEscaner {
  private teclas: { tecla: string; t: number }[] = []
  private opciones: OpcionesEscaner

  constructor(opciones: OpcionesEscaner = OPCIONES_ESCANER) {
    this.opciones = opciones
  }

  /** Registra una tecla. Con Enter devuelve el escaneo si el ritmo fue de escáner, o null. */
  tecla(evento: KeyboardEvent): Escaneo | null {
    const t = evento.timeStamp
    const ultima = this.teclas[this.teclas.length - 1]
    if (ultima && t - ultima.t > this.opciones.maxPausaMs) this.teclas = []

    if (evento.key === 'Enter') {
      const teclas = this.teclas
      this.teclas = []
      if (teclas.length < this.opciones.minCaracteres) return null
      const ritmoMs = (teclas[teclas.length - 1].t - teclas[0].t) / (teclas.length - 1)
      return { codigo: teclas.map((k) => k.tecla).join(''), ritmoMs }
    }
    if (evento.key.length === 1) {
      this.teclas.push({ tecla: evento.key, t })
    } else if (!MODIFICADORAS.has(evento.key)) {
      // Shift y compañía no cortan el escaneo: el escáner las usa para mayúsculas y símbolos.
      this.teclas = []
    }
    return null
  }
}
