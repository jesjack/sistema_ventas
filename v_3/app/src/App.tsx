import { useCallback, useEffect, type CSSProperties, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { NexBadge, NexButton, NexCheckbox, NexCombobox, NexDatePicker, NexInput, NexMorph, NexProvider, NexSegmented, NexSelect, toIsoDate } from '@nexfluid/react'
import { NexSheets, type Workbook } from '@nexfluid/react/sheets'
import { ALTO_FILA_HOJA, CARRIL_HOJA, FORMATOS_CARRITO, FORMATOS_VENTAS, IDIOMA_HOJAS, altoHojaCarrito, filasVentasQueCaben, altoHojaVentas, anchosCarrito, anchosVentas, libroDeCarrito, libroDeVentas, medidorDeTexto, type LineaVenta } from './hojas.ts'
import { useAltoDisponible, useMarcoHoja } from './marcoHoja.ts'
import { Icono } from './iconos.tsx'
import { PanelCodigos, PanelRegistro } from './codigos.tsx'
import { PanelCatalogo } from './catalogo.tsx'
import { PanelBotones } from './adminBotones.tsx'
import type { NexCorner, NexMotion, NexRadius } from '@nexfluid/react'
import { agregarAlCarrito, dinero, leerNumero, totalDelCarrito, type FilaCarrito } from './carrito.ts'
import { DetectorEscaner, type Escaneo } from './escaner.ts'
import { iniciarDepuracionGota } from './depurarGota.ts'
import { medirConsulta, medirTecla, Serie, type Resumen } from './medicion.ts'

interface InfoBase {
  ruta: string
  productos: number
  codigos: number
  usuario: string | null
  sesion_id: number | null
}

/** Producto del catálogo (núcleo: `nucleo::Producto`). */
interface Producto {
  id: number
  nombre: string
}

/** Una denominación del corte de caja (comando `denominaciones`). */
interface Denominacion {
  tipo: 'BILLETE' | 'MONEDA'
  valor: number
  texto: string
}

/** Un botón configurable (núcleo: `nucleo::botones::Boton`). */
interface Boton {
  id: number
  nombre_interno: string
  etiqueta: string
  accion: string
  orden: number
}

/** Cuándo y quién (núcleo: `UsoCodigo`). */
interface UsoCodigo {
  en: string
  usuario: string | null
}

/** Un código de la reserva, sin el código (núcleo: `CodigoCaja`). */
interface CodigoCaja {
  id: number
  creado_en: string
  creado_por: string | null
  usado: UsoCodigo | null
  retirado: UsoCodigo | null
}

/** Lo que devuelve `estado_caja` (D21, D23). */
interface EstadoCaja {
  permisos: string[]
  como_abrir: 'permiso' | 'ventana_diaria' | 'codigo'
  codigos: { disponibles: number; ultimo_uso: UsoCodigo | null }
  pocos_codigos: number
  administra_codigos: boolean
  ve_otros_dias: boolean
  /** El último corte, si nadie ha vendido después (badge de CORTE DE CAJA). */
  corte_listo: { id: number; fecha: string; hora: string; total: number } | null
  /** El corte con el que empieza hoy y su verificación (la empleada cuenta el cambio). */
  corte_de_hoy: {
    id: number
    fecha: string
    hora: string
    total: number
    usuario: string | null
    verificacion: { en: string; contado: number; usuario: string | null } | null
  } | null
}

/** Ancho de los modales; el alto es el de su contenido (NexMorph `size="content"`). */
const ESTILO_MODAL: CSSProperties = { width: 'min(460px, calc(100vw - 32px))' }

/** Las pantallas de la caja (arriba de todo): la venta, las ventas realizadas y el desarrollador. */
type Vista = 'carrito' | 'ventas' | 'botones' | 'desarrollador'

const TEXTO_AUTORIZACION: Record<string, string> = {
  permiso: 'con tu permiso sin límite',
  ventana_diaria: 'para contar el cambio (una vez al día, antes de la primera venta)',
  codigo: 'con el código autorizado',
}

/** Venta registrada por el comando `cobrar`. */
interface VentaRegistrada {
  venta_id: number
  total: number
  recibido: number
  cambio: number
}

interface ProductoConPrecio {
  producto: string
  precio: number
}

/**
 * Al enfocar con la etiqueta (o por código) el navegador deja el cursor al principio del texto.
 * Si quedó ahí, se lleva al final. Un clic sobre el texto coloca el cursor después del foco, así
 * que lo respeta; y si el navegador seleccionó todo (Tab), tampoco se toca.
 */
function cursorAlFinal(e: FocusEvent<HTMLInputElement>) {
  const campo = e.currentTarget
  if (campo.value && campo.selectionStart === 0 && campo.selectionEnd === 0) {
    campo.setSelectionRange(campo.value.length, campo.value.length)
  }
}

type Aviso = { tono: 'success' | 'warning' | 'danger' | 'neutral'; texto: string }

const TEMAS = ['editorial-light', 'editorial-dark', 'pulse-light', 'pulse-dark', 'monochrome-ink', 'chromatic-fluid']
const MOVIMIENTOS: NexMotion[] = ['none', 'subtle', 'fluid', 'elastic']

const serieTeclas = new Serie()
const serieConsultas = new Serie()

export default function App() {
  const [tema, setTema] = useState('editorial-light')
  const [movimiento, setMovimiento] = useState<NexMotion>('fluid')
  const [depurarGota, setDepurarGota] = useState(false)
  const [gotaSimetrica, setGotaSimetrica] = useState(true)
  const [hoverMembrana, setHoverMembrana] = useState(true)
  const [redondez, setRedondez] = useState<NexRadius | 'tema'>('md')
  const [esquina, setEsquina] = useState<NexCorner | 'tema'>('tema')
  const [gotaAncho, setGotaAncho] = useState(0.6)
  const [gotaEstiramiento, setGotaEstiramiento] = useState(0.35)

  const [producto, setProducto] = useState('')
  const [precio, setPrecio] = useState('')
  const [cantidad, setCantidad] = useState('1')
  const [sugerencias, setSugerencias] = useState<Producto[]>([])
  const [carrito, setCarrito] = useState<FilaCarrito[]>([])
  // Botones configurables de la columna derecha (P1) y el panel de desarrollador.
  const [botones, setBotones] = useState<Boton[]>([])
  const [vista, setVista] = useState<Vista>('carrito')
  // Códigos de barras: el escaneado que no estaba (se registra) y VER CÓDIGOS.
  const [registroCodigo, setRegistroCodigo] = useState<string | null>(null)
  const [verCodigosBarras, setVerCodigosBarras] = useState(false)
  const [verCatalogo, setVerCatalogo] = useState(false)
  // Pago exacto: se pide una segunda confirmación (Intro otra vez).
  const [confirmarExacto, setConfirmarExacto] = useState<null | 'normal' | 'sinTicket'>(null)
  // Solo lectura (como la tabla de la hoja de Calc en la v2): se deriva del carrito. Los anchos se
  // ajustan al contenido y al ancho disponible (Producto ocupa lo que sobra: sin hueco a la derecha).
  const refHoja = useRef<HTMLDivElement>(null)
  const marcoHoja = useMarcoHoja(refHoja, [vista])
  const libroCarrito = useMemo<Workbook>(() => {
    const nodo = refHoja.current
    if (!nodo || !marcoHoja.anchoUtil) return libroDeCarrito(carrito)
    return libroDeCarrito(carrito, anchosCarrito(carrito, marcoHoja.anchoUtil, medidorDeTexto(nodo)))
  }, [carrito, marcoHoja.anchoUtil, marcoHoja.fuentes])
  const [fechas, setFechas] = useState<string[]>([])
  const [fecha, setFecha] = useState<string | null>(null)
  const [lineasVenta, setLineasVenta] = useState<LineaVenta[]>([])
  const [aviso, setAviso] = useState<Aviso | null>(null)
  const [cobro, setCobro] = useState<string | null>(null)
  // Apertura del cajón y código de autorización (D21, D23).
  const [estadoCaja, setEstadoCaja] = useState<EstadoCaja | null>(null)
  const [pideCodigo, setPideCodigo] = useState<string | null>(null)
  // CÓDIGOS DE CAJA: el modal para administrar la reserva (quien tiene "sin límite").
  const [verCodigos, setVerCodigos] = useState(false)
  const [listaCodigos, setListaCodigos] = useState<CodigoCaja[]>([])
  const [codigoNuevo, setCodigoNuevo] = useState('')
  const [turnoPerdido, setTurnoPerdido] = useState(false)
  const refCodigo = useRef<HTMLInputElement>(null)
  const refCodigoNuevo = useRef<HTMLInputElement>(null)

  const [info, setInfo] = useState<InfoBase | null>(null)
  const [errorBase, setErrorBase] = useState<string | null>(null)
  const [resumenTeclas, setResumenTeclas] = useState<Resumen | null>(null)
  const [resumenConsultas, setResumenConsultas] = useState<Resumen | null>(null)
  const [escaneos, setEscaneos] = useState<(Escaneo & { encontrado: boolean })[]>([])

  const refProducto = useRef<HTMLInputElement>(null)
  const refPrecio = useRef<HTMLInputElement>(null)
  const refRecibido = useRef<HTMLInputElement>(null)
  const consultaActual = useRef(0)

  const total = useMemo(() => totalDelCarrito(carrito), [carrito])
  const opciones = useMemo(() => sugerencias.map((p) => ({ value: String(p.id), label: p.nombre })), [sugerencias])

  useEffect(() => (depurarGota ? iniciarDepuracionGota() : undefined), [depurarGota])

  // VENTAS REALIZADAS: hoy (desde el último corte) y los días anteriores. Se recargan al cobrar.
  const [recargaVentas, setRecargaVentas] = useState(0)
  useEffect(() => {
    invoke<string[]>('fechas_con_ventas').then(
      (lista) => {
        setFechas(lista)
        setFecha((f) => f ?? lista[0] ?? null)
      },
      (e) => setAviso({ tono: 'danger', texto: `No se pudieron leer las fechas de venta: ${e}` }),
    )
  }, [recargaVentas])
  useEffect(() => {
    if (!fecha) return
    invoke<LineaVenta[]>('ventas_del_dia', { fecha }).then(setLineasVenta, (e) =>
      setAviso({ tono: 'danger', texto: `No se pudieron leer las ventas: ${e}` }),
    )
  }, [fecha, recargaVentas])
  // VENTAS REALIZADAS como hoja de solo lectura, igual que el carrito.
  const refVentas = useRef<HTMLDivElement>(null)
  const marcoVentas = useMarcoHoja(refVentas, [lineasVenta.length > 0, vista])
  const altoVentas = useAltoDisponible(refVentas, 24, [lineasVenta.length > 0, vista])
  const libroVentas = useMemo<Workbook>(() => {
    const nodo = refVentas.current
    if (!nodo || !marcoVentas.anchoUtil) return libroDeVentas(lineasVenta)
    // Si no caben todas las filas habrá carril vertical: se le reserva su ancho desde ya, para que
    // las columnas no se desborden a lo ancho cuando aparezca.
    const desborda = lineasVenta.length > filasVentasQueCaben(marcoVentas.extraAlto, altoVentas)
    const ancho = marcoVentas.anchoUtil - (desborda ? CARRIL_HOJA : 0)
    return libroDeVentas(lineasVenta, anchosVentas(lineasVenta, ancho, medidorDeTexto(nodo)))
  }, [lineasVenta, marcoVentas.anchoUtil, marcoVentas.extraAlto, marcoVentas.fuentes, altoVentas])
  // Lo más reciente abajo, como en la hoja de la v2: al cargar o al cobrar, se baja al final.
  useEffect(() => {
    const vista = refVentas.current?.querySelector<HTMLElement>('.nx-sheet__viewport')
    if (vista) requestAnimationFrame(() => (vista.scrollTop = vista.scrollHeight))
  }, [lineasVenta, vista])

  useEffect(() => {
    invoke<InfoBase>('info_base').then(setInfo, (e) => setErrorBase(String(e)))
  }, [])

  // Lee las mediciones cada medio segundo (medir no provoca renders).
  useEffect(() => {
    const id = setInterval(() => {
      setResumenTeclas(serieTeclas.resumen())
      setResumenConsultas(serieConsultas.resumen())
    }, 500)
    return () => clearInterval(id)
  }, [])

  // Autocompletado: Rust busca en el catálogo en cada cambio; se descartan las respuestas viejas.
  // NexCombobox decide cuándo mostrar la lista (se abre al escribir, no al elegir).
  useEffect(() => {
    const texto = producto.trim()
    const numero = ++consultaActual.current
    if (!texto) {
      setSugerencias([])
      return
    }
    medirConsulta(serieConsultas, () => invoke<Producto[]>('buscar_productos', { texto })).then(
      (lista) => {
        if (numero !== consultaActual.current) return
        setSugerencias(lista)
      },
      (e) => setAviso({ tono: 'danger', texto: `Error al buscar: ${e}` }),
    )
  }, [producto])

  const enfocarProducto = () => requestAnimationFrame(() => refProducto.current?.focus())

  const leerBotones = useCallback(() => {
    invoke<Boton[]>('botones').then(setBotones, () => setBotones([]))
  }, [])
  useEffect(() => leerBotones(), [leerBotones])

  // El estado de la caja: permisos, cómo se abriría el cajón y cuántos códigos quedan (el botón
  // CÓDIGOS DE CAJA avisa con su badge; ya no se interrumpe con un modal).
  const leerEstadoCaja = useCallback(() => {
    invoke<EstadoCaja>('estado_caja').then(setEstadoCaja, () => setEstadoCaja(null))
  }, [])
  useEffect(() => leerEstadoCaja(), [leerEstadoCaja])

  // D8: otra caja tomó el turno. Rust cierra la sesión y la app en unos segundos.
  useEffect(() => {
    const quitar = listen('turno-perdido', () => setTurnoPerdido(true))
    return () => void quitar.then((f) => f())
  }, [])

  // Abrir caja (y Intro con el carrito vacío, D23). Fase 3: el cajón real; hoy, simulado.
  const abrirCaja = async (codigo?: string) => {
    try {
      const autorizacion = await invoke<string>('abrir_caja', { codigo: codigo ?? null })
      setPideCodigo(null)
      setAviso({ tono: 'success', texto: `Caja abierta ${TEXTO_AUTORIZACION[autorizacion] ?? autorizacion} (cajón simulado).` })
      setRecargaVentas((n) => n + 1)
      leerEstadoCaja()
      enfocarProducto()
    } catch (e) {
      if (String(e) === 'PIDE_CODIGO') {
        setPideCodigo('')
        requestAnimationFrame(() => refCodigo.current?.focus())
        return
      }
      setAviso({ tono: 'warning', texto: String(e) })
      setPideCodigo(null)
      leerEstadoCaja()
      enfocarProducto()
    }
  }

  const [errorCodigos, setErrorCodigos] = useState<string | null>(null)
  const leerCodigos = () =>
    invoke<CodigoCaja[]>('codigos_caja').then(
      (lista) => {
        setListaCodigos(lista)
        setErrorCodigos(null)
      },
      (e) => setErrorCodigos(String(e)),
    )
  const abrirCodigos = () => {
    setCodigoNuevo('')
    setErrorCodigos(null)
    setVerCodigos(true)
    void leerCodigos()
    requestAnimationFrame(() => refCodigoNuevo.current?.focus())
  }
  const cerrarCodigos = () => {
    setVerCodigos(false)
    enfocarProducto()
  }
  const agregarCodigo = async () => {
    try {
      await invoke('agregar_codigo', { codigo: codigoNuevo })
      setCodigoNuevo('')
      await leerCodigos()
      leerEstadoCaja()
      refCodigoNuevo.current?.focus()
    } catch (e) {
      setErrorCodigos(String(e))
    }
  }
  const retirarCodigo = async (id: number) => {
    try {
      await invoke('retirar_codigo', { id })
      await leerCodigos()
      leerEstadoCaja()
    } catch (e) {
      setErrorCodigos(String(e))
    }
  }

  const limpiarEntrada = () => {
    setProducto('')
    setPrecio('')
    setCantidad('1')
  }

  const agregar = (nombre: string, valorPrecio: number, valorCantidad: number) => {
    const siguiente = agregarAlCarrito(carrito, nombre, valorPrecio, valorCantidad)
    if (!siguiente) return false
    setCarrito(siguiente)
    return true
  }

  const intentarAgregar = () => {
    const nombre = producto.trim()
    const valorPrecio = leerNumero(precio)
    const valorCantidad = Number.parseInt(cantidad, 10)
    if (!nombre) {
      setAviso({ tono: 'warning', texto: 'Falta el producto.' })
      enfocarProducto()
      return
    }
    if (!(valorPrecio > 0)) {
      setAviso({ tono: 'warning', texto: 'Falta el precio, o no es un número.' })
      refPrecio.current?.focus()
      return
    }
    if (!(valorCantidad > 0)) {
      setAviso({ tono: 'warning', texto: 'La cantidad debe ser un número mayor que cero.' })
      return
    }
    agregar(nombre, valorPrecio, valorCantidad)
    setAviso(null)
    limpiarEntrada()
    enfocarProducto()
  }

  const abrirCobro = () => {
    setConfirmarExacto(null)
    setCobro('')
    requestAnimationFrame(() => refRecibido.current?.focus())
  }

  // El núcleo valida el cobro (mismas reglas y textos que la v2) y registra la venta en la base.
  const [cobrando, setCobrando] = useState(false)
  const confirmarCobro = async (sinTicket = false) => {
    if (cobrando) return
    setCobrando(true)
    try {
      const venta = await invoke<VentaRegistrada>('cobrar', {
        items: carrito.map(({ producto, precio, cantidad }) => ({ producto, precio, cantidad })),
        recibido: cobro ?? '',
        sinTicket,
      })
      setAviso({
        tono: 'success',
        texto: sinTicket
          ? `Venta #${venta.venta_id} registrada sin ticket: ${dinero(venta.total)}.`
          : `Venta #${venta.venta_id} registrada: ${dinero(venta.total)}, recibido ${dinero(venta.recibido)}, cambio ${dinero(venta.cambio)}.`,
      })
      setCarrito([])
      setCobro(null)
      setConfirmarExacto(null)
      setRecargaVentas((n) => n + 1)
      leerEstadoCaja()
      enfocarProducto()
    } catch (e) {
      setAviso({ tono: 'warning', texto: String(e) })
      requestAnimationFrame(() => refRecibido.current?.select())
    } finally {
      setCobrando(false)
    }
  }

  const procesarEscaneo = useCallback(async (escaneo: Escaneo) => {
    // El escáner tecleó el código en el campo enfocado: se quita de ahí.
    const quitar = (v: string) => (v.endsWith(escaneo.codigo) ? v.slice(0, -escaneo.codigo.length) : v)
    setProducto(quitar)
    setPrecio(quitar)
    setCantidad((v) => quitar(v) || '1')
    try {
      const registro = await medirConsulta(serieConsultas, () =>
        invoke<ProductoConPrecio | null>('buscar_codigo', { codigo: escaneo.codigo }),
      )
      setEscaneos((lista) => [{ ...escaneo, encontrado: registro !== null }, ...lista].slice(0, 6))
      if (registro) {
        setCarrito((c) => agregarAlCarrito(c, registro.producto, registro.precio, 1) ?? c)
        setAviso({ tono: 'success', texto: `Escaneado: ${registro.producto} (${dinero(registro.precio)})` })
      } else {
        // Como la v2: se registra (producto y precio). Además, la v3 lo agrega al carrito.
        setRegistroCodigo(escaneo.codigo)
      }
    } catch (e) {
      setAviso({ tono: 'danger', texto: `Error al buscar el código: ${e}` })
    }
  }, [])

  // Teclado de toda la ventana: mide cada tecla y separa los escaneos del tecleo.
  useEffect(() => {
    const detector = new DetectorEscaner()
    const alTeclear = (e: KeyboardEvent) => {
      medirTecla(e, serieTeclas)
      const escaneo = detector.tecla(e)
      if (escaneo) {
        e.preventDefault()
        e.stopPropagation()
        void procesarEscaneo(escaneo)
      }
    }
    window.addEventListener('keydown', alTeclear, { capture: true })
    return () => window.removeEventListener('keydown', alTeclear, { capture: true })
  }, [procesarEscaneo])

  // Lectura directa del escáner (Rust, evdev): llega aunque otra app tenga el foco, y la ventana
  // pide pasar al frente. Apagada por defecto mientras la v2 sea la oficial (ver escaner.rs).
  const [escanerDirecto, setEscanerDirecto] = useState<{ activo: boolean; estado: string } | null>(null)
  useEffect(() => {
    const quitar = listen<string>('escaneo', (e) => {
      setVista('carrito')
      void procesarEscaneo({ codigo: e.payload, ritmoMs: 0 })
    })
    return () => void quitar.then((f) => f())
  }, [procesarEscaneo])
  useEffect(() => {
    const leer = () => invoke<{ activo: boolean; estado: string }>('estado_escaner').then(setEscanerDirecto, () => {})
    leer()
    const id = setInterval(leer, 2000)
    return () => clearInterval(id)
  }, [])

  // Solo llegan las teclas que NexCombobox no usó: Intro con la lista cerrada.
  const teclaProducto = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (producto.trim()) refPrecio.current?.focus()
      else if (carrito.length) abrirCobro()
      else void abrirCaja() // D23: Intro con el carrito vacío sigue las reglas del botón Abrir caja
    }
  }

  const teclaAgregar = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      intentarAgregar()
    }
  }

  // D15/D17: Intro es siempre el cobro normal; sin ticket solo con su tecla (F4) o un clic.
  const teclaCobro = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      cobrarCon('normal')
    } else if (e.key === 'F4') {
      e.preventDefault()
      cobrarCon('sinTicket')
    } else if (e.key === 'Escape' && confirmarExacto) {
      // Escape en la confirmación vuelve a pedir lo recibido (NexMorph no cierra si se previene).
      e.preventDefault()
      setConfirmarExacto(null)
    }
  }

  // Sin escribir lo recibido (pago exacto), se pide confirmarlo: la misma tecla otra vez (Intro, o
  // F4 sin ticket). Con una cantidad escrita, cobra directo.
  const cobrarCon = (modo: 'normal' | 'sinTicket') => {
    const sinCantidad = cobro === null || cobro.trim() === ''
    if (sinCantidad && confirmarExacto !== modo) {
      setConfirmarExacto(modo)
      return
    }
    void confirmarCobro(modo === 'sinTicket')
  }
  const cerrarCobro = () => {
    setCobro(null)
    setConfirmarExacto(null)
    enfocarProducto()
  }

  const hoy = toIsoDate(new Date())
  const recibido = cobro === null || cobro.trim() === '' ? total : leerNumero(cobro)

  // ---- Corte de caja (como la v2): se abre el cajón, se escribe el cambio que se queda en la caja
  // (piezas de cada billete y moneda), se confirma (Intro = Regresar) y VENTAS REALIZADAS de hoy
  // empieza con ese cambio. El ticket del corte llega con las impresoras (fase 3).
  const [denominaciones, setDenominaciones] = useState<Denominacion[]>([])
  useEffect(() => {
    invoke<Denominacion[]>('denominaciones').then(setDenominaciones, () => {})
  }, [])
  const [corte, setCorte] = useState<{ cantidades: string[]; confirmar: boolean; error: string | null } | null>(null)
  const refPrimeraPieza = useRef<HTMLInputElement>(null)
  const refRegresar = useRef<HTMLButtonElement>(null)
  const piezas = (texto: string): number | null => (texto.trim() === '' ? 0 : /^\d+$/.test(texto.trim()) ? Number(texto.trim()) : null)
  const totalCorte = corte
    ? denominaciones.reduce((suma, d, i) => suma + d.valor * (piezas(corte.cantidades[i] ?? '') ?? 0), 0)
    : 0
  const abrirCorte = async () => {
    try {
      await invoke('abrir_caja_para_corte')
      setRecargaVentas((n) => n + 1)
      setCorte({ cantidades: denominaciones.map(() => ''), confirmar: false, error: null })
      requestAnimationFrame(() => refPrimeraPieza.current?.focus())
    } catch (e) {
      setAviso({ tono: 'warning', texto: String(e) })
    }
  }
  const cerrarCorte = () => {
    setCorte(null)
    enfocarProducto()
  }
  // Paso 1 → 2: se revisa lo escrito (mismos textos que la v2) y se pide confirmar.
  const pedirConfirmacionCorte = () => {
    if (!corte) return
    const mala = denominaciones.findIndex((_, i) => piezas(corte.cantidades[i] ?? '') === null)
    if (mala >= 0) {
      const d = denominaciones[mala]!
      setCorte({
        ...corte,
        error: `La cantidad de ${d.tipo.toLowerCase()}s de ${d.texto} no es válida: escriba cuántas piezas hay (un número entero) o déjelo vacío.`,
      })
      return
    }
    setCorte({ ...corte, confirmar: true, error: null })
    requestAnimationFrame(() => refRegresar.current?.focus())
  }
  // ---- Verificar el corte con el que empieza el día: la empleada cuenta el cambio y dice si cuadra.
  const [verificando, setVerificando] = useState<{ noCuadra: boolean; contado: string; error: string | null } | null>(null)
  const refContado = useRef<HTMLInputElement>(null)
  const corteHoy = estadoCaja?.corte_de_hoy ?? null
  const cerrarVerificacion = () => {
    setVerificando(null)
    enfocarProducto()
  }
  const guardarVerificacion = async (contado: string) => {
    if (!corteHoy || !verificando) return
    try {
      const evento = await invoke<string>('verificar_corte', { corteId: corteHoy.id, contado })
      setVerificando(null)
      setAviso({ tono: evento.endsWith('CUADRA') ? 'success' : 'warning', texto: `Quedó registrado: ${evento}.` })
      setRecargaVentas((n) => n + 1)
      leerEstadoCaja()
      enfocarProducto()
    } catch (e) {
      setVerificando({ ...verificando, error: String(e) })
    }
  }
  const contadoVerificacion = verificando?.contado.trim() ? leerNumero(verificando.contado) : NaN
  const modalVerificacion = corteHoy && (
              <NexMorph.Target label="Verificar corte" className="caja__modal" size="content" panelStyle={ESTILO_MODAL}>
                {/* El panel se monta en <body>, fuera del NexProvider de la caja: se repite la forma. */}
                <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
                  <div className="caja__cobro">
                    <p className="caja__cobro-total">Cambio esperado: {dinero(corteHoy.total)}</p>
                    <p className="caja__nota">
                      Corte {corteHoy.usuario ? `de ${corteHoy.usuario}, ` : ''}del {corteHoy.fecha} a las {corteHoy.hora.slice(0, 5)}. Cuenta el
                      cambio de la caja (puedes abrirla con tu apertura del día) y di si cuadra. El desglose está al inicio de VENTAS REALIZADAS.
                    </p>
                    {verificando?.noCuadra ? (
                      <>
                        <NexInput
                          ref={refContado}
                          label="¿Cuánto hay de cambio en la caja?"
                          description={
                            Number.isFinite(contadoVerificacion)
                              ? contadoVerificacion < corteHoy.total
                                ? `Faltan ${dinero(corteHoy.total - contadoVerificacion)}`
                                : contadoVerificacion > corteHoy.total
                                  ? `Sobran ${dinero(contadoVerificacion - corteHoy.total)}`
                                  : 'Cuadra'
                              : 'Intro guarda · Escape cierra'
                          }
                          error={verificando.error ?? undefined}
                          inputMode="decimal"
                          leading="$"
                          autoComplete="off"
                          value={verificando.contado}
                          onChange={(e) => setVerificando({ ...verificando, contado: e.target.value, error: null })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              void guardarVerificacion(verificando.contado)
                            }
                          }}
                        />
                        <div className="caja__cobro-acciones">
                          <NexButton appearance="filled" onClick={() => void guardarVerificacion(verificando.contado)}>
                            Guardar (Intro)
                          </NexButton>
                          <NexButton appearance="ghost" onClick={() => setVerificando({ noCuadra: false, contado: '', error: null })}>
                            Regresar
                          </NexButton>
                        </div>
                      </>
                    ) : (
                      <>
                        {verificando?.error && (
                          <p className="caja__aviso caja__aviso--danger" role="alert">
                            {verificando.error}
                          </p>
                        )}
                        <div className="caja__cobro-acciones">
                          <NexButton appearance="filled" onClick={() => void guardarVerificacion('')}>
                            Cuadra
                          </NexButton>
                          <NexButton
                            appearance="outlined"
                            tone="danger"
                            onClick={() => {
                              setVerificando({ noCuadra: true, contado: '', error: null })
                              requestAnimationFrame(() => refContado.current?.focus())
                            }}
                          >
                            No cuadra
                          </NexButton>
                          <NexButton appearance="ghost" onClick={() => void abrirCaja()}>
                            Abrir caja para contar
                          </NexButton>
                        </div>
                      </>
                    )}
                  </div>
                </NexProvider>
              </NexMorph.Target>
  )

  const hacerCorte = async () => {
    if (!corte) return
    try {
      const resumen = await invoke<string>('hacer_corte', { cantidades: corte.cantidades })
      setCorte(null)
      leerEstadoCaja()
      setAviso({ tono: 'success', texto: `Corte de caja hecho. Cambio en caja: ${resumen}. (Ticket del corte: fase 3.)` })
      setFecha(hoy)
      setVista('ventas')
      setRecargaVentas((n) => n + 1)
      enfocarProducto()
    } catch (e) {
      setCorte({ ...corte, confirmar: false, error: String(e) })
    }
  }

  // Lo que hace cada acción de botón (`archivo_accion` de la v2). Las que aún no existen en la v3
  // devuelven el motivo y el botón se muestra deshabilitado.
  const accion = (nombre: string): (() => void) | string => {
    switch (nombre) {
      case 'cobrar_carrito':
        // Como la v2: con el carrito vacío, cobrar es abrir la caja (con sus reglas, D23).
        return () => (carrito.length ? abrirCobro() : void abrirCaja())
      case 'limpiar_carrito':
        return () => {
          setCarrito([])
          limpiarEntrada()
          setAviso({ tono: 'neutral', texto: 'Carrito vacío.' })
          enfocarProducto()
        }
      case 'abrir_caja':
        return () => void abrirCaja()
      case 'ver_ventas':
        return () => setVista('ventas')
      case 'ping':
        return () => setAviso({ tono: 'neutral', texto: 'pong' })
      case 'corte_de_caja':
        return () => void abrirCorte()
      case 'ver_codigos_de_barras':
        return () => setVerCodigosBarras(true)
      case 'autocompletado':
        return () => setVerCatalogo(true)
      case 'imprimir_codigo_de_barras':
      case 'imprimir_varios_codigos':
        return 'Llega con las impresoras (fase 3).'
      case 'ver_camaras':
        return 'Llega con las cámaras (fase 5).'
      default:
        return `Acción desconocida en esta versión: ${nombre}.`
    }
  }
  const esDesarrollador = estadoCaja?.permisos.includes('desarrollador') ?? false

  // Cada acción de botón; las que abren un modal lo hacen desde su botón (NexMorph: la superficie
  // crece desde él). Si el usuario no tiene ese botón, el modal aparece igual, sin origen.
  const tieneBoton = (nombre: string) => botones.some((b) => b.accion === nombre)
  const modalCobro = (
              <NexMorph.Target label="Cobrar" className="caja__modal" size="content" panelStyle={ESTILO_MODAL}>
                {/* El panel se monta en <body>, fuera del NexProvider de la caja: se repite la forma. */}
                <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
                  <div className="caja__cobro">
                    <p className="caja__cobro-total">Cobrar {dinero(total)}</p>
                    <NexInput
                      ref={refRecibido}
                      label="Recibido"
                      description="Intro sin escribir nada = pago exacto · F4 sin ticket · Escape cancela"
                      inputMode="decimal"
                      leading="$"
                      value={cobro ?? ''}
                      autoComplete="off"
                      onChange={(e) => {
                        setCobro(e.target.value)
                        setConfirmarExacto(null)
                      }}
                      onKeyDown={teclaCobro}
                      onFocus={cursorAlFinal}
                    />
                    <p className="caja__cambio">
                      Cambio: <strong>{recibido >= total ? dinero(recibido - total) : '—'}</strong>
                    </p>
                    {confirmarExacto && (
                      <p className="caja__aviso caja__aviso--warning" role="alert">
                        {confirmarExacto === 'sinTicket'
                          ? `¿Cobrar ${dinero(total)} sin ticket, pago exacto? F4 otra vez para cobrar`
                          : `¿Pago exacto de ${dinero(total)}, sin cambio? Intro otra vez para cobrar`}{' '}
                        · Escape para escribir lo recibido
                      </p>
                    )}
                    <div className="caja__cobro-acciones">
                      <NexButton appearance="filled" onClick={() => cobrarCon('normal')} disabled={cobrando}>
                        {confirmarExacto === 'normal' ? 'Sí, pago exacto (Intro)' : 'Cobrar (Intro)'}
                      </NexButton>
                      <NexButton appearance="outlined" onClick={() => cobrarCon('sinTicket')} disabled={cobrando}>
                        {confirmarExacto === 'sinTicket' ? 'Sí, sin ticket (F4)' : 'Sin ticket (F4)'}
                      </NexButton>
                      <NexButton appearance="ghost" onClick={cerrarCobro}>Cancelar</NexButton>
                    </div>
                  </div>
                </NexProvider>
              </NexMorph.Target>
  )
  const modalCodigo = (
              <NexMorph.Target label="Código de autorización" className="caja__modal" size="content" panelStyle={ESTILO_MODAL}>
                {/* El panel se monta en <body>, fuera del NexProvider de la caja: se repite la forma. */}
                <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
                  <div className="caja__cobro">
                    <p className="caja__cobro-total">Abrir caja con código</p>
                    <NexInput
                      ref={refCodigo}
                      label="Código de autorización"
                      description="Lo da quien tiene permiso para abrir la caja. Sirve una sola vez · Escape cancela"
                      type="password"
                      autoComplete="off"
                      value={pideCodigo ?? ''}
                      onChange={(e) => setPideCodigo(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          void abrirCaja(pideCodigo ?? '')
                        }
                      }}
                    />
                    <div className="caja__cobro-acciones">
                      <NexButton appearance="filled" onClick={() => void abrirCaja(pideCodigo ?? '')}>
                        Abrir caja (Intro)
                      </NexButton>
                      <NexButton appearance="ghost" onClick={() => (setPideCodigo(null), enfocarProducto())}>Cancelar</NexButton>
                    </div>
                  </div>
                </NexProvider>
              </NexMorph.Target>
  )
  // Corte: cinco billetes y las monedas (en pesos) en una cuadrícula de 3 × 2, la etiqueta arriba
  // de cada campo (los $ quedan alineados) y el subtotal debajo.
  const celdasCorte = denominaciones.map((d, i) => {
    const n = piezas(corte?.cantidades[i] ?? '')
    return (
      <NexInput
        key={i}
        ref={i === 0 ? refPrimeraPieza : undefined}
        label={d.tipo === 'MONEDA' ? 'Monedas (pesos)' : `Billetes de ${d.texto}`}
        description={n === null ? '¿?' : n ? `= ${dinero(d.valor * n)}` : '\u00a0'}
        inputMode="numeric"
        autoComplete="off"
        value={corte?.cantidades[i] ?? ''}
        disabled={corte?.confirmar}
        onChange={(e) =>
          corte && setCorte({ ...corte, error: null, cantidades: corte.cantidades.map((c, j) => (j === i ? e.target.value : c)) })
        }
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            pedirConfirmacionCorte()
          }
        }}
      />
    )
  })
  const modalCorte = (
              <NexMorph.Target label="Corte de caja" className="caja__modal" size="content" panelStyle={{ width: 'min(560px, calc(100vw - 32px))' }}>
                {/* El panel se monta en <body>, fuera del NexProvider de la caja: se repite la forma. */}
                <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
                  <div className="caja__cobro">
                    <p className="caja__cobro-total">Corte de caja</p>
                    <p className="caja__nota">
                      Escriba cuántos billetes de cada uno se quedan en la caja como cambio, y cuánto suman las monedas en pesos.
                      Lo que no haya, déjelo vacío. Intro sigue.
                    </p>
                    <div className="caja__corte">{celdasCorte}</div>
                    <p className="caja__corte-total">Total de cambio: {dinero(totalCorte)}</p>
                    {corte?.error && (
                      <p className="caja__aviso caja__aviso--danger" role="alert">
                        {corte.error}
                      </p>
                    )}
                    {corte?.confirmar ? (
                      <>
                        <p className="caja__aviso caja__aviso--warning" role="alert">
                          Se hará el corte con {dinero(totalCorte)} de cambio en la caja. Las ventas de hoy hechas hasta ahora
                          dejarán de verse en la tabla (siguen guardadas y se pueden revisar eligiendo el día).
                        </p>
                        <div className="caja__cobro-acciones">
                          <NexButton ref={refRegresar} appearance="filled" onClick={() => corte && setCorte({ ...corte, confirmar: false })}>
                            Regresar (Intro)
                          </NexButton>
                          <NexButton appearance="outlined" tone="danger" onClick={() => void hacerCorte()}>
                            Hacer el corte
                          </NexButton>
                        </div>
                      </>
                    ) : (
                      <div className="caja__cobro-acciones">
                        <NexButton appearance="filled" onClick={pedirConfirmacionCorte}>
                          Hacer corte (Intro)
                        </NexButton>
                        <NexButton appearance="ghost" onClick={cerrarCorte}>
                          Cancelar
                        </NexButton>
                      </div>
                    )}
                  </div>
                </NexProvider>
              </NexMorph.Target>
  )
  const botonDe = (b: Boton) => {
    const hacer = accion(b.accion)
    const deshabilitado = typeof hacer === 'string' || turnoPerdido
    const boton = (
      <NexButton
        key={b.id}
        appearance={b.accion === 'cobrar_carrito' ? 'filled' : 'default'}
        fullWidth
        contentAlign="start"
        iconStart={<Icono nombre={b.accion} />}
        disabled={deshabilitado}
        title={typeof hacer === 'string' ? hacer : undefined}
        onClick={typeof hacer === 'string' ? undefined : hacer}
      >
        <span className="caja__boton-texto">{b.etiqueta}</span>
      </NexButton>
    )
    if (b.accion === 'cobrar_carrito')
      return (
        <NexMorph key={b.id} open={cobro !== null} onOpenChange={(abierto) => !abierto && cerrarCobro()}>
          <NexMorph.Source>{boton}</NexMorph.Source>
          {modalCobro}
        </NexMorph>
      )
    if (b.accion === 'abrir_caja')
      return (
        <NexMorph key={b.id} open={pideCodigo !== null} onOpenChange={(abierto) => !abierto && (setPideCodigo(null), enfocarProducto())}>
          <NexMorph.Source>{boton}</NexMorph.Source>
          {modalCodigo}
        </NexMorph>
      )
    if (b.accion === 'autocompletado')
      return (
        <NexMorph key={b.id} open={verCatalogo} onOpenChange={(abierto) => !abierto && (setVerCatalogo(false), enfocarProducto())}>
          <NexMorph.Source>{boton}</NexMorph.Source>
          <NexMorph.Target label="Catálogo" className="caja__modal" size="content" panelStyle={{ width: 'min(720px, calc(100vw - 32px))' }}>
            <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
              <PanelCatalogo cerrar={() => (setVerCatalogo(false), enfocarProducto())} />
            </NexProvider>
          </NexMorph.Target>
        </NexMorph>
      )
    if (b.accion === 'ver_codigos_de_barras')
      return (
        <NexMorph key={b.id} open={verCodigosBarras} onOpenChange={(abierto) => !abierto && (setVerCodigosBarras(false), enfocarProducto())}>
          <NexMorph.Source>{boton}</NexMorph.Source>
          <NexMorph.Target label="Códigos de barras" className="caja__modal" size="content" panelStyle={{ width: 'min(760px, calc(100vw - 32px))' }}>
            <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
              <PanelCodigos cerrar={() => (setVerCodigosBarras(false), enfocarProducto())} />
            </NexProvider>
          </NexMorph.Target>
        </NexMorph>
      )
    if (b.accion === 'corte_de_caja')
      return (
        <NexMorph key={b.id} open={corte !== null} onOpenChange={(abierto) => !abierto && cerrarCorte()}>
          <NexMorph.Source>
            {/* Badge: "Listo $…" mientras nadie venda después del último corte; si no, "Sin corte". */}
            <div className="caja__con-badge">
              {boton}
              {estadoCaja && (
                <NexBadge
                  className="caja__badge-esquina"
                  appearance="filled"
                  tone={estadoCaja.corte_listo ? 'success' : 'warning'}
                  title={
                    estadoCaja.corte_listo
                      ? `Corte del ${estadoCaja.corte_listo.fecha} a las ${estadoCaja.corte_listo.hora.slice(0, 5)}; nadie ha vendido después`
                      : 'Se vendió después del último corte (o no hay corte)'
                  }
                >
                  {estadoCaja.corte_listo ? `Listo ${dinero(estadoCaja.corte_listo.total)}` : 'Sin corte'}
                </NexBadge>
              )}
            </div>
          </NexMorph.Source>
          {modalCorte}
        </NexMorph>
      )
    return boton
  }

  const conVentas = useMemo(() => new Set(fechas), [fechas])

  return (
    <NexProvider
      theme={tema}
      motion={movimiento}
      density="comfortable"
      liquid={gotaSimetrica ? 'symmetric' : 'spring'}
      hitArea={hoverMembrana ? 'membrane' : 'box'}
      radius={redondez === 'tema' ? undefined : redondez}
      corner={esquina === 'tema' ? undefined : esquina}
      canvas
      className="caja"
      style={
        {
          '--nx-liquid-thin': String(gotaAncho),
          '--nx-liquid-stretch': String(gotaEstiramiento),
        } as CSSProperties
      }
    >
      <main className="caja__cuerpo">
        <section className="caja__venta" aria-label="Caja">
          <NexSegmented
            aria-label="Pantalla"
            density="compact"
            value={vista}
            onValueChange={(v) => setVista(v as Vista)}
            options={[
              { value: 'carrito', label: 'Carrito' },
              { value: 'ventas', label: 'Ver ventas' },
              ...(esDesarrollador
                ? [
                    { value: 'botones', label: 'Botones' },
                    { value: 'desarrollador', label: 'Desarrollador' },
                  ]
                : []),
            ]}
          />

          {turnoPerdido && (
            <p className="caja__aviso caja__aviso--danger" role="alert">
              Otra caja tomó el turno. Esta caja se cierra en unos segundos (las ventas ya registradas quedan guardadas).
            </p>
          )}




          {aviso && (
            <p className={`caja__aviso caja__aviso--${aviso.tono}`} role="status">
              {aviso.texto}
            </p>
          )}

          {/* El corte con el que empieza el día: mientras nadie lo verifique, se avisa con su botón. */}
          {vista === 'carrito' && corteHoy && !corteHoy.verificacion && (
            <div className="caja__verificar">
              <span>
                Cambio esperado en la caja: <strong>{dinero(corteHoy.total)}</strong> · corte
                {corteHoy.usuario ? ` de ${corteHoy.usuario}` : ''} del {corteHoy.fecha} a las {corteHoy.hora.slice(0, 5)}, sin verificar
              </span>
              <NexMorph open={verificando !== null} onOpenChange={(abierto) => !abierto && cerrarVerificacion()}>
                <NexMorph.Source>
                  <NexButton appearance="outlined" density="compact" onClick={() => setVerificando({ noCuadra: false, contado: '', error: null })}>
                    Verificar corte
                  </NexButton>
                </NexMorph.Source>
                {modalVerificacion}
              </NexMorph>
            </div>
          )}
          {vista === 'carrito' && corteHoy?.verificacion && (
            <p className="caja__nota">
              Corte del {corteHoy.fecha} verificado
              {corteHoy.verificacion.usuario ? ` por ${corteHoy.verificacion.usuario}` : ''} el {corteHoy.verificacion.en}: se contaron{' '}
              {dinero(corteHoy.verificacion.contado)} de {dinero(corteHoy.total)}.
            </p>
          )}

          {vista === 'carrito' && (
            <>
              <div className="caja__entrada">
                <NexCombobox
                  ref={refProducto}
                  label="Producto"
                  value={producto}
                  options={opciones}
                  filter={false}
                  tabSelects
                  autoFocus
                  onValueChange={setProducto}
                  onOptionSelect={() => requestAnimationFrame(() => refPrecio.current?.focus())}
                  onKeyDown={teclaProducto}
                  onFocus={cursorAlFinal}
                />
                <NexInput
                  ref={refPrecio}
                  label="Precio"
                  inputMode="decimal"
                  value={precio}
                  leading="$"
                  autoComplete="off"
                  onChange={(e) => setPrecio(e.target.value)}
                  onKeyDown={teclaAgregar}
                  onFocus={cursorAlFinal}
                />
                <NexInput
                  label="Cantidad"
                  inputMode="numeric"
                  value={cantidad}
                  autoComplete="off"
                  onChange={(e) => setCantidad(e.target.value)}
                  onKeyDown={teclaAgregar}
                  onFocus={cursorAlFinal}
                />
              </div>

              <div ref={refHoja} className={carrito.length ? 'caja__marco-hoja' : 'caja__marco-hoja caja__marco-hoja--vacio'}>
                <NexSheets
                  className="caja__hoja"
                  workbook={libroCarrito}
                  readOnly
                  extent={false}
                  height={altoHojaCarrito(carrito, marcoHoja.extraAlto)}
                  label="Carrito"
                  columnLabels="name"
                  columnFormats={FORMATOS_CARRITO}
                  locale={IDIOMA_HOJAS}
                  tabs={false}
                  statusBar={false}
                  toolbar={false}
                  formulaBar={false}
                />
                {/* Como en la v2: con el carrito vacío, la fila se ve como una sola celda con el aviso
                    (NexSheets no fusiona celdas: se cubre la fila). */}
                {carrito.length === 0 && (
                  <div className="caja__carrito-vacio" style={{ height: ALTO_FILA_HOJA - 1, left: marcoHoja.anchoRotulos }}>
                    El carrito está vacío
                  </div>
                )}
              </div>

              <div className="caja__total">
                <span>Total</span>
                <strong>{dinero(total)}</strong>
              </div>
            </>
          )}

          {vista === 'ventas' && (
            <section className="caja__ventas" aria-label="Ventas realizadas">
              <div className="caja__ventas-cabecera">
                <h2>{estadoCaja?.ve_otros_dias ? 'Ventas realizadas' : 'Ventas de hoy'}</h2>
                {estadoCaja?.ve_otros_dias && (
                  <NexDatePicker
                    label="Día"
                    hideLabel
                    locale="es-MX"
                    value={fecha}
                    onValueChange={setFecha}
                    max={hoy}
                    isDateMarked={(d) => conVentas.has(d)}
                    format={{ weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }}
                  />
                )}
              </div>
              <div ref={refVentas}>
                {lineasVenta.length ? (
                  <NexSheets
                    className="caja__hoja caja__hoja--ventas"
                    workbook={libroVentas}
                    readOnly
                    extent={false}
                    height={altoHojaVentas(lineasVenta, marcoVentas.extraAlto, altoVentas)}
                    label={`Ventas del ${fecha}`}
                    columnLabels="name"
                    columnFormats={FORMATOS_VENTAS}
                    locale={IDIOMA_HOJAS}
                    tabs={false}
                    statusBar={false}
                    toolbar={false}
                    formulaBar={false}
                  />
                ) : (
                  <p className="caja__nota">No hay ventas ese día.</p>
                )}
              </div>
            </section>
          )}

          {vista === 'botones' && esDesarrollador && <PanelBotones alCambiar={leerBotones} />}

          {vista === 'desarrollador' && esDesarrollador && (
            <section className="caja__medicion" aria-label="Desarrollador">
              <Medida titulo="Tecla → pantalla" resumen={resumenTeclas} nota="incluye hasta 1 cuadro (≈16 ms)" />
              <Medida titulo="Consulta a Rust" resumen={resumenConsultas} nota="autocompletado y códigos" />

              <h3>Escaneos</h3>
              {escaneos.length === 0 ? (
                <p className="caja__nota">Escanea algo para ver su ritmo.</p>
              ) : (
                <ul className="caja__escaneos">
                  {escaneos.map((e, i) => (
                    <li key={i}>
                      <code>{e.codigo}</code> · {e.ritmoMs.toFixed(1)} ms/tecla · {e.encontrado ? 'registrado' : 'no registrado'}
                    </li>
                  ))}
                </ul>
              )}

              <NexButton
                appearance="outlined"
                tabIndex={-1}
                onClick={() => {
                  serieTeclas.limpiar()
                  serieConsultas.limpiar()
                  setEscaneos([])
                }}
              >
                Reiniciar mediciones
              </NexButton>

              <h3>Escáner</h3>
              <NexCheckbox
                label="Lectura directa del escáner"
                description="Lo toma en exclusiva y lee aunque otra app tenga el foco (la caja pide pasar al frente). Mientras esté encendido, la v2 NO recibe el escáner."
                checked={escanerDirecto?.activo ?? false}
                onChange={(e) =>
                  void invoke<{ activo: boolean; estado: string }>('escaner_directo', { activar: e.target.checked }).then(setEscanerDirecto)
                }
              />
              {escanerDirecto && <p className="caja__nota">Estado: {escanerDirecto.estado}</p>}

              <h3>Aspecto</h3>
              <NexSelect
                label="Tema"
                value={tema}
                onValueChange={setTema}
                options={TEMAS.map((t) => ({ value: t, label: t }))}
              />
              <NexSelect
                label="Movimiento"
                value={movimiento}
                onValueChange={(v) => setMovimiento(v as NexMotion)}
                options={MOVIMIENTOS.map((m) => ({ value: m, label: m }))}
              />
              <NexCheckbox
                label="Depurar gota"
                description="Rastro verde del borde derecho de la gota, un punto por cuadro"
                checked={depurarGota}
                onChange={(e) => setDepurarGota(e.target.checked)}
              />
              <NexCheckbox
                label="Gota simétrica"
                description='liquid="symmetric": igual al salir que al llegar (fluid completa, subtle a un tercio, elastic sin cambio)'
                checked={gotaSimetrica}
                onChange={(e) => setGotaSimetrica(e.target.checked)}
              />
              <NexSelect
                label="Redondez de los controles"
                value={redondez}
                onValueChange={(v) => setRedondez(v as NexRadius | 'tema')}
                options={[
                  { value: 'tema', label: 'Del tema (cápsula)' },
                  { value: 'none', label: 'none · 0' },
                  { value: 'sm', label: 'sm · 6 px' },
                  { value: 'md', label: 'md · 10 px' },
                  { value: 'lg', label: 'lg · 16 px' },
                  { value: 'pill', label: 'pill · cápsula' },
                ]}
              />
              <NexSelect
                label="Curva de la esquina"
                value={esquina}
                onValueChange={(v) => setEsquina(v as NexCorner | 'tema')}
                options={[
                  { value: 'tema', label: 'Del tema (round)' },
                  { value: 'round', label: 'round · círculo' },
                  { value: 'squircle', label: 'squircle · superelipse' },
                ]}
              />
              <NexCheckbox
                label="Hover sigue la membrana"
                description='hitArea="membrane": la parte abombada de los botones también responde al puntero'
                checked={hoverMembrana}
                onChange={(e) => setHoverMembrana(e.target.checked)}
              />
              <Deslizador titulo="Ancho a mitad del viaje" valor={gotaAncho} min={0.3} max={1} paso={0.05} cambiar={setGotaAncho} />
              <Deslizador
                titulo="Estiramiento"
                valor={gotaEstiramiento}
                min={0}
                max={1}
                paso={0.05}
                cambiar={setGotaEstiramiento}
                desactivado={!gotaSimetrica}
              />
              {info && (
                <p className="caja__nota">
                  Base: {info.ruta} · {info.productos} productos · {info.codigos} códigos
                </p>
              )}
            </section>
          )}
        </section>

        <aside className="caja__botones" aria-label="Botones">
          {botones.map(botonDe)}
          {botones.length === 0 && <p className="caja__nota">Este usuario no tiene botones asignados.</p>}
          {/* Código escaneado que no estaba registrado: producto y precio (como la v2). */}
          <NexMorph open={registroCodigo !== null} onOpenChange={(abierto) => !abierto && (setRegistroCodigo(null), enfocarProducto())}>
            {registroCodigo !== null && (
              <NexMorph.Target label="Registrar código" className="caja__modal" size="content" panelStyle={ESTILO_MODAL}>
                <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
                  <PanelRegistro
                    key={registroCodigo}
                    codigo={registroCodigo}
                    cancelar={() => (setRegistroCodigo(null), enfocarProducto())}
                    registrado={(c) => {
                      setRegistroCodigo(null)
                      setCarrito((actual) => agregarAlCarrito(actual, c.producto, c.precio, 1) ?? actual)
                      setAviso({ tono: 'success', texto: `Código ${c.codigo} registrado: ${c.producto} (${dinero(c.precio)}). Se agregó al carrito.` })
                      enfocarProducto()
                    }}
                  />
                </NexProvider>
              </NexMorph.Target>
            )}
          </NexMorph>
          {!tieneBoton('cobrar_carrito') && (
            <NexMorph open={cobro !== null} onOpenChange={(abierto) => !abierto && cerrarCobro()}>
              {modalCobro}
            </NexMorph>
          )}
          {!tieneBoton('abrir_caja') && (
            <NexMorph open={pideCodigo !== null} onOpenChange={(abierto) => !abierto && (setPideCodigo(null), enfocarProducto())}>
              {modalCodigo}
            </NexMorph>
          )}
          {estadoCaja?.administra_codigos && (
            <NexMorph open={verCodigos} onOpenChange={(abierto) => !abierto && cerrarCodigos()}>
              <NexMorph.Source>
                {/* El badge va en la esquina superior derecha del botón, encima: no le quita espacio al texto. */}
                <div className="caja__con-badge">
                  <NexButton
                    fullWidth
                    contentAlign="start"
                    iconStart={<Icono nombre="codigos_caja" />}
                    disabled={turnoPerdido}
                    onClick={abrirCodigos}
                  >
                    <span className="caja__boton-texto">CÓDIGOS DE CAJA</span>
                  </NexButton>
                  <BadgeCodigos estado={estadoCaja} />
                </div>
              </NexMorph.Source>
              <NexMorph.Target label="Códigos de caja" className="caja__modal" size="content" panelStyle={ESTILO_MODAL}>
                {/* El panel se monta en <body>, fuera del NexProvider de la caja: se repite la forma. */}
                <NexProvider radius={redondez === 'tema' ? undefined : redondez} corner={esquina === 'tema' ? undefined : esquina}>
                  <div className="caja__cobro">
                    <p className="caja__cobro-total">Códigos de caja</p>
                    <p className="caja__nota">
                      La empleada escribe cualquiera de los disponibles para abrir la caja fuera de su apertura diaria;
                      cada código sirve una sola vez. Se guardan cifrados: aquí no se pueden volver a ver.
                    </p>
                    <NexInput
                      ref={refCodigoNuevo}
                      label="Agregar un código"
                      description="Al menos 4 caracteres · Intro lo agrega · Escape cierra"
                      type="password"
                      autoComplete="new-password"
                      value={codigoNuevo}
                      error={errorCodigos ?? undefined}
                      onChange={(e) => {
                        setCodigoNuevo(e.target.value)
                        setErrorCodigos(null)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          void agregarCodigo()
                        }
                      }}
                    />
                    <ul className="caja__codigos">
                      {listaCodigos.length === 0 && <li className="caja__nota">Todavía no hay códigos.</li>}
                      {listaCodigos.map((c) => (
                        <li key={c.id} className="caja__codigo" data-estado={c.usado ? 'usado' : c.retirado ? 'retirado' : 'disponible'}>
                          <span>
                            <strong>Código #{c.id}</strong>{' '}
                            {c.usado
                              ? `· usado el ${c.usado.en}${c.usado.usuario ? ` por ${c.usado.usuario}` : ''}`
                              : c.retirado
                                ? `· retirado el ${c.retirado.en}${c.retirado.usuario ? ` por ${c.retirado.usuario}` : ''}`
                                : `· disponible, agregado el ${c.creado_en}${c.creado_por ? ` por ${c.creado_por}` : ''}`}
                          </span>
                          {!c.usado && !c.retirado && (
                            <NexButton appearance="ghost" tone="danger" density="compact" onClick={() => void retirarCodigo(c.id)}>
                              Retirar
                            </NexButton>
                          )}
                        </li>
                      ))}
                    </ul>
                    <div className="caja__cobro-acciones">
                      <NexButton appearance="filled" onClick={() => void agregarCodigo()}>
                        Agregar (Intro)
                      </NexButton>
                      <NexButton appearance="ghost" onClick={cerrarCodigos}>
                        Cerrar
                      </NexButton>
                    </div>
                  </div>
                </NexProvider>
              </NexMorph.Target>
            </NexMorph>
          )}
          <div className="caja__sesion">
            {info ? (
              <NexBadge tone="success" dot>
                {info.usuario ? `${info.usuario} · sesión ${info.sesion_id}` : 'sin sesión'}
              </NexBadge>
            ) : (
              <NexBadge tone="danger" dot>
                {errorBase ?? 'Abriendo la base…'}
              </NexBadge>
            )}
          </div>
        </aside>
      </main>
    </NexProvider>
  )
}

function Deslizador(props: {
  titulo: string
  valor: number
  min: number
  max: number
  paso: number
  cambiar: (v: number) => void
  desactivado?: boolean
}) {
  return (
    <label className="caja__deslizador">
      <span>
        {props.titulo} <strong>{props.valor.toFixed(2)}</strong>
      </span>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.paso}
        value={props.valor}
        disabled={props.desactivado}
        onChange={(e) => props.cambiar(Number(e.target.value))}
      />
    </label>
  )
}

function Medida({ titulo, resumen, nota }: { titulo: string; resumen: Resumen | null; nota: string }) {
  return (
    <div className="caja__medida">
      <span className="caja__medida-titulo">{titulo}</span>
      {resumen ? (
        <span>
          mediana <strong>{resumen.mediana.toFixed(1)} ms</strong> · p95 {resumen.p95.toFixed(1)} · máx{' '}
          {resumen.max.toFixed(1)} <span className="caja__nota">({resumen.n})</span>
        </span>
      ) : (
        <span className="caja__nota">sin datos</span>
      )}
      <span className="caja__nota">{nota}</span>
    </div>
  )
}

/** Badge del botón CÓDIGOS DE CAJA: cuántos quedan; ámbar si son pocos, rojo si no queda ninguno. */
function BadgeCodigos({ estado }: { estado: EstadoCaja }) {
  const n = estado.codigos.disponibles
  const tono = n === 0 ? 'danger' : n <= estado.pocos_codigos ? 'warning' : 'neutral'
  return (
    <NexBadge className="caja__badge-esquina" appearance="filled" tone={tono} title={n === 0 ? 'No quedan códigos para la empleada' : `Quedan ${n}`}>
      {n === 0 ? 'Sin códigos' : n}
    </NexBadge>
  )
}
