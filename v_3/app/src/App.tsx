import { useCallback, useEffect, type CSSProperties, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { NexBadge, NexButton, NexCheckbox, NexCombobox, NexInput, NexProvider, NexSegmented, NexSelect } from '@nexfluid/react'
import { NexDataView, NexSheets, type Workbook } from '@nexfluid/react/sheets'
import { altoHojaCarrito, anchosCarrito, hojaDeVentas, libroDeCarrito, medidorDeTexto, type LineaVenta } from './hojas.ts'
import type { NexCorner, NexMotion, NexRadius } from '@nexfluid/react'
import { agregarAlCarrito, dinero, leerNumero, totalDelCarrito, type FilaCarrito } from './carrito.ts'
import { DetectorEscaner, type Escaneo } from './escaner.ts'
import { iniciarDepuracionGota } from './depurarGota.ts'
import { medirConsulta, medirTecla, Serie, type Resumen } from './medicion.ts'

interface InfoBase {
  ruta: string
  productos: number
  codigos: number
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
  const [movimiento, setMovimiento] = useState<NexMotion>('subtle')
  const [depurarGota, setDepurarGota] = useState(false)
  const [gotaSimetrica, setGotaSimetrica] = useState(true)
  const [hoverMembrana, setHoverMembrana] = useState(true)
  const [redondez, setRedondez] = useState<NexRadius | 'tema'>('tema')
  const [esquina, setEsquina] = useState<NexCorner | 'tema'>('tema')
  const [gotaAncho, setGotaAncho] = useState(0.6)
  const [gotaEstiramiento, setGotaEstiramiento] = useState(0.35)

  const [producto, setProducto] = useState('')
  const [precio, setPrecio] = useState('')
  const [cantidad, setCantidad] = useState('1')
  const [sugerencias, setSugerencias] = useState<string[]>([])
  const [carrito, setCarrito] = useState<FilaCarrito[]>([])
  // Prueba de NexSheets (P2): el carrito puede verse como tabla propia o como hoja editable.
  const [vistaCarrito, setVistaCarrito] = useState<'tabla' | 'hoja'>('tabla')
  // Solo lectura (como la tabla de la hoja de Calc en la v2): se deriva del carrito. Los anchos se
  // ajustan al contenido y al ancho disponible (Producto ocupa lo que sobra: sin hueco a la derecha).
  const refHoja = useRef<HTMLDivElement>(null)
  // Medidas reales de la hoja, sin estimar: el ancho útil del área de la tabla (sin la columna de
  // números de fila) y lo que ocupa todo lo que no es la tabla (barra de fórmulas, bordes).
  const [marcoHoja, setMarcoHoja] = useState({ anchoUtil: 0, extraAlto: 0 })
  useEffect(() => {
    const nodo = refHoja.current
    if (!nodo) return
    const medir = () => {
      const editor = nodo.querySelector<HTMLElement>('.nx-sheets')
      const vista = nodo.querySelector<HTMLElement>('.nx-sheet__viewport')
      const esquina = nodo.querySelector<HTMLElement>('.nx-sheet__corner')
      if (!editor || !vista) return
      // Medido por FUERA de la zona con scroll (offsetWidth/offsetHeight incluyen sus barras): si
      // se midiera por dentro, una barra que aparece cambia la medida, el ajuste la vuelve a
      // provocar y las dos barras se sostienen solas.
      const anchoUtil = vista.offsetWidth - (esquina?.offsetWidth ?? 0)
      const extraAlto = editor.offsetHeight - vista.offsetHeight
      setMarcoHoja((m) => (m.anchoUtil === anchoUtil && m.extraAlto === extraAlto ? m : { anchoUtil, extraAlto }))
    }
    medir()
    const observador = new ResizeObserver(medir)
    observador.observe(nodo)
    return () => observador.disconnect()
  }, [vistaCarrito])
  const libroCarrito = useMemo<Workbook>(() => {
    const nodo = refHoja.current
    if (!nodo || !marcoHoja.anchoUtil) return libroDeCarrito(carrito)
    return libroDeCarrito(carrito, anchosCarrito(carrito, marcoHoja.anchoUtil, medidorDeTexto(nodo)))
  }, [carrito, marcoHoja.anchoUtil])
  const [fechas, setFechas] = useState<string[]>([])
  const [fecha, setFecha] = useState<string | null>(null)
  const [lineasVenta, setLineasVenta] = useState<LineaVenta[]>([])
  const [aviso, setAviso] = useState<Aviso | null>(null)
  const [cobro, setCobro] = useState<string | null>(null)

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
  const opciones = useMemo(() => sugerencias.map((s) => ({ value: s, label: s })), [sugerencias])

  useEffect(() => (depurarGota ? iniciarDepuracionGota() : undefined), [depurarGota])

  // VENTAS REALIZADAS (solo lectura sobre la copia de la base).
  useEffect(() => {
    invoke<string[]>('fechas_con_ventas').then(
      (lista) => {
        setFechas(lista)
        setFecha((f) => f ?? lista[0] ?? null)
      },
      (e) => setAviso({ tono: 'danger', texto: `No se pudieron leer las fechas de venta: ${e}` }),
    )
  }, [])
  useEffect(() => {
    if (!fecha) return
    invoke<LineaVenta[]>('ventas_del_dia', { fecha }).then(setLineasVenta, (e) =>
      setAviso({ tono: 'danger', texto: `No se pudieron leer las ventas: ${e}` }),
    )
  }, [fecha])
  const hojaVentas = useMemo(() => hojaDeVentas(lineasVenta), [lineasVenta])

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
    medirConsulta(serieConsultas, () => invoke<string[]>('buscar_productos', { texto })).then(
      (lista) => {
        if (numero !== consultaActual.current) return
        setSugerencias(lista)
      },
      (e) => setAviso({ tono: 'danger', texto: `Error al buscar: ${e}` }),
    )
  }, [producto])

  const enfocarProducto = () => requestAnimationFrame(() => refProducto.current?.focus())

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
    setCobro('')
    requestAnimationFrame(() => refRecibido.current?.focus())
  }

  const confirmarCobro = () => {
    const recibido = cobro === null || cobro.trim() === '' ? total : leerNumero(cobro)
    if (!(recibido >= total)) {
      setAviso({ tono: 'warning', texto: `Lo recibido no alcanza: faltan ${dinero(total - (recibido || 0))}.` })
      return
    }
    setAviso({
      tono: 'success',
      texto: `Venta simulada por ${dinero(total)}, cambio ${dinero(recibido - total)}. No se guardó en ninguna base.`,
    })
    setCarrito([])
    setCobro(null)
    enfocarProducto()
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
        setAviso({
          tono: 'warning',
          texto: `El código ${escaneo.codigo} no está registrado. En la v3 aquí se abriría el registro del código.`,
        })
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

  // Solo llegan las teclas que NexCombobox no usó: Intro con la lista cerrada.
  const teclaProducto = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (producto.trim()) refPrecio.current?.focus()
      else if (carrito.length) abrirCobro()
    }
  }

  const teclaAgregar = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      intentarAgregar()
    }
  }

  const teclaCobro = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      confirmarCobro()
    } else if (e.key === 'Escape') {
      setCobro(null)
      enfocarProducto()
    }
  }

  const recibido = cobro === null || cobro.trim() === '' ? total : leerNumero(cobro)

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
      <header className="caja__cabecera">
        <div>
          <h1 className="caja__titulo">Caja V3</h1>
          <p className="caja__sub">Prototipo de la fase 0 · solo lectura sobre una copia de la base</p>
        </div>
        {info ? (
          <NexBadge tone="success" dot>
            {info.productos} productos · {info.codigos} códigos
          </NexBadge>
        ) : (
          <NexBadge tone="danger" dot>
            {errorBase ?? 'Abriendo la base…'}
          </NexBadge>
        )}
      </header>

      <main className="caja__cuerpo">
        <section className="caja__venta" aria-label="Venta">
          <div className="caja__entrada">
            <NexCombobox
              ref={refProducto}
              label="Producto"
              value={producto}
              options={opciones}
              filter={false}
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

          <p className="caja__ayuda">
            Enter en Producto pasa al precio · Enter en Precio o Cantidad agrega · Enter con Producto vacío cobra ·
            el escáner funciona en cualquier campo
          </p>

          {aviso && (
            <p className={`caja__aviso caja__aviso--${aviso.tono}`} role="status">
              {aviso.texto}
            </p>
          )}

          <div className="caja__vista">
            <NexSegmented
              aria-label="Vista del carrito"
              value={vistaCarrito}
              onValueChange={(v) => setVistaCarrito(v as 'tabla' | 'hoja')}
              options={[
                { value: 'tabla', label: 'Tabla propia' },
                { value: 'hoja', label: 'NexSheets' },
              ]}
            />
          </div>
          {vistaCarrito === 'tabla' ? (
            <table className="caja__carrito">
              <thead>
                <tr>
                  <th>Producto</th>
                  <th className="num">Precio</th>
                  <th className="num">Cantidad</th>
                  <th className="num">Subtotal</th>
                  <th aria-label="Acciones" />
                </tr>
              </thead>
              <tbody>
                {carrito.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="caja__vacio">
                      El carrito está vacío
                    </td>
                  </tr>
                ) : (
                  carrito.map((f, i) => (
                    <tr key={`${f.producto}|${f.precio}`}>
                      <td>{f.producto}</td>
                      <td className="num">{dinero(f.precio)}</td>
                      <td className="num">{f.cantidad}</td>
                      <td className="num">{dinero(f.subtotal)}</td>
                      <td className="num">
                        <NexButton
                          appearance="ghost"
                          tone="danger"
                          density="compact"
                          tabIndex={-1}
                          onClick={() => setCarrito((c) => c.filter((_, j) => j !== i))}
                        >
                          Quitar
                        </NexButton>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          ) : (
            <div ref={refHoja}>
            <NexSheets
              className="caja__hoja"
              workbook={libroCarrito}
              readOnly
              extent={false}
              height={altoHojaCarrito(carrito, marcoHoja.extraAlto)}
              label="Carrito"
              tabs={false}
              statusBar={false}
              toolbar={false}
            />
            </div>
          )}

          <div className="caja__total">
            <span>Total</span>
            <strong>{dinero(total)}</strong>
          </div>

          {cobro !== null && (
            <div className="caja__cobro" role="dialog" aria-label="Cobrar">
              <p className="caja__cobro-total">Cobrar {dinero(total)}</p>
              <NexInput
                ref={refRecibido}
                label="Recibido"
                description="Enter sin escribir nada = pago exacto · Escape cancela"
                inputMode="decimal"
                leading="$"
                value={cobro}
                autoComplete="off"
                onChange={(e) => setCobro(e.target.value)}
                onKeyDown={teclaCobro}
                onFocus={cursorAlFinal}
              />
              <p className="caja__cambio">
                Cambio: <strong>{recibido >= total ? dinero(recibido - total) : '—'}</strong>
              </p>
            </div>
          )}

          <section className="caja__ventas" aria-label="Ventas realizadas">
            <div className="caja__ventas-cabecera">
              <h2>Ventas realizadas</h2>
              <NexSelect
                label="Día"
                hideLabel
                value={fecha}
                onValueChange={setFecha}
                options={fechas.map((f) => ({ value: f, label: f }))}
                placeholder="Sin ventas"
              />
            </div>
            {lineasVenta.length ? (
              <>
                <NexDataView sheet={hojaVentas} title={`Ventas del ${fecha}`} controls={false} view="table" />
              </>
            ) : (
              <p className="caja__nota">No hay ventas ese día.</p>
            )}
          </section>
        </section>

        <aside className="caja__medicion" aria-label="Mediciones">
          <h2>Mediciones</h2>
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
          {info && <p className="caja__nota">Base: {info.ruta}</p>}
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
