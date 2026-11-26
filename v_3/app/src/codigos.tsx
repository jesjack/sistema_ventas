// Códigos de barras, como la v2: registrar uno que se escaneó y no estaba (producto y precio de
// venta), y VER CÓDIGOS (buscar por código o producto, editar código, producto o precio).
// Las reglas y los mensajes están en Rust (`registrar_codigo`, `actualizar_codigo`).

import { useEffect, useRef, useState, type Ref } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { NexButton, NexCombobox, NexInput } from '@nexfluid/react'
import { dinero } from './carrito.ts'
import { AvisoSugerencia } from './catalogo.tsx'

export interface CodigoBarras {
  id: number
  codigo: string
  producto_id: number
  producto: string
  precio: number
  creado_en: string | null
}

interface Producto {
  id: number
  nombre: string
}

/** Producto del catálogo con autocompletado (Tab elige). Si se escribe uno que no está, `id` es null. */
function BuscadorProducto(props: {
  nombre: string
  cambiar: (nombre: string, id: number | null) => void
  alElegir?: () => void
  refCampo?: Ref<HTMLInputElement>
  autoFocus?: boolean
}) {
  const [opciones, setOpciones] = useState<Producto[]>([])
  const consulta = useRef(0)
  useEffect(() => {
    const texto = props.nombre.trim()
    const n = ++consulta.current
    if (!texto) {
      setOpciones([])
      return
    }
    invoke<Producto[]>('buscar_productos', { texto }).then((lista) => n === consulta.current && setOpciones(lista), () => {})
  }, [props.nombre])
  const campo = (
    <NexCombobox
      ref={props.refCampo}
      label="Producto"
      description="Elige uno del catálogo (Tab); si escribes uno que no está, se agrega al catálogo."
      value={props.nombre}
      options={opciones.map((p) => ({ value: String(p.id), label: p.nombre }))}
      filter={false}
      tabSelects
      autoFocus={props.autoFocus}
      onValueChange={(v) => props.cambiar(v, null)}
      onOptionSelect={(o) => {
        props.cambiar(o.label, Number(o.value))
        props.alElegir?.()
      }}
    />
  )
  // Si se escribe un producto que no está, el corrector sugiere antes de agregarlo al catálogo.
  return props.nombre.trim() && !opciones.some((p) => p.nombre.toLowerCase() === props.nombre.trim().toLowerCase()) ? (
    <>
      {campo}
      <AvisoSugerencia nombre={props.nombre} usar={(s) => props.cambiar(s, null)} />
    </>
  ) : (
    campo
  )
}

/** Registrar un código escaneado que no estaba. `registrado` recibe el registro (para el carrito). */
export function PanelRegistro(props: { codigo: string; registrado: (c: CodigoBarras) => void; cancelar: () => void }) {
  const [producto, setProducto] = useState<{ nombre: string; id: number | null }>({ nombre: '', id: null })
  const [precio, setPrecio] = useState('')
  const [error, setError] = useState<string | null>(null)
  const refPrecio = useRef<HTMLInputElement>(null)
  const registrar = async () => {
    try {
      const c = await invoke<CodigoBarras>('registrar_codigo', {
        codigo: props.codigo,
        productoId: producto.id,
        producto: producto.nombre,
        precio,
      })
      props.registrado(c)
    } catch (e) {
      setError(String(e))
    }
  }
  return (
    <div className="caja__cobro">
      <p className="caja__cobro-total">Código nuevo</p>
      <p className="caja__nota">
        El código <strong>{props.codigo}</strong> no está registrado. Elige el producto y su precio de venta: queda registrado y se
        agrega al carrito.
      </p>
      <BuscadorProducto
        nombre={producto.nombre}
        autoFocus
        cambiar={(nombre, id) => {
          setProducto({ nombre, id })
          setError(null)
        }}
        alElegir={() => requestAnimationFrame(() => refPrecio.current?.focus())}
      />
      <NexInput
        ref={refPrecio}
        label="Precio de venta"
        inputMode="decimal"
        leading="$"
        autoComplete="off"
        value={precio}
        error={error ?? undefined}
        onChange={(e) => {
          setPrecio(e.target.value)
          setError(null)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            void registrar()
          }
        }}
      />
      <div className="caja__cobro-acciones">
        <NexButton appearance="filled" onClick={() => void registrar()}>
          Registrar (Intro)
        </NexButton>
        <NexButton appearance="ghost" onClick={props.cancelar}>
          Cancelar
        </NexButton>
      </div>
    </div>
  )
}

const fechaCorta = (texto: string | null) => (texto ? texto.slice(0, 16).replace('T', ' ') : '')

/** VER CÓDIGOS: la lista con su buscador y la edición de uno. */
export function PanelCodigos(props: { cerrar: () => void }) {
  const [filtro, setFiltro] = useState('')
  const [lista, setLista] = useState<{ codigos: CodigoBarras[]; total: number }>({ codigos: [], total: 0 })
  const [editando, setEditando] = useState<CodigoBarras | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const refBuscar = useRef<HTMLInputElement>(null)
  const leer = (texto: string) =>
    invoke<{ codigos: CodigoBarras[]; total: number }>('codigos_barras', { filtro: texto }).then(setLista, (e) => setAviso(String(e)))
  useEffect(() => {
    void leer(filtro)
  }, [filtro])
  useEffect(() => {
    requestAnimationFrame(() => refBuscar.current?.focus())
  }, [])

  if (editando)
    return (
      <EditarCodigo
        codigo={editando}
        listo={(guardado) => {
          setEditando(null)
          if (guardado) setAviso('Cambios guardados.')
          void leer(filtro)
          requestAnimationFrame(() => refBuscar.current?.focus())
        }}
      />
    )

  const conteo =
    lista.codigos.length === lista.total
      ? `${lista.total} código${lista.total === 1 ? '' : 's'}`
      : `${lista.codigos.length} de ${lista.total} códigos`
  return (
    <div className="caja__cobro">
      <p className="caja__cobro-total">Códigos de barras registrados</p>
      <NexInput
        ref={refBuscar}
        label="Buscar"
        description={conteo}
        placeholder="Código o producto"
        autoComplete="off"
        value={filtro}
        onChange={(e) => {
          setFiltro(e.target.value)
          setAviso(null)
        }}
      />
      <div className="caja__tabla-codigos">
        <table>
          <thead>
            <tr>
              <th>Código</th>
              <th>Producto</th>
              <th className="num">Precio</th>
              <th>Registrado</th>
              <th aria-label="Acciones" />
            </tr>
          </thead>
          <tbody>
            {lista.codigos.map((c) => (
              <tr key={c.id}>
                <td className="caja__mono">{c.codigo}</td>
                <td>{c.producto}</td>
                <td className="num">{dinero(c.precio)}</td>
                <td className="caja__nota">{fechaCorta(c.creado_en)}</td>
                <td className="num">
                  <NexButton appearance="ghost" density="compact" onClick={() => setEditando(c)}>
                    Editar
                  </NexButton>
                </td>
              </tr>
            ))}
            {lista.codigos.length === 0 && (
              <tr>
                <td colSpan={5} className="caja__vacio">
                  {lista.total ? 'Ningún código coincide.' : 'Todavía no hay códigos registrados.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {aviso && <p className="caja__nota">{aviso}</p>}
      <div className="caja__cobro-acciones">
        <NexButton appearance="ghost" onClick={props.cerrar}>
          Cerrar
        </NexButton>
      </div>
    </div>
  )
}

/** Editar un código: texto, producto o precio (como "Editar..." de la v2). */
function EditarCodigo(props: { codigo: CodigoBarras; listo: (guardado: boolean) => void }) {
  const [codigo, setCodigo] = useState(props.codigo.codigo)
  const [producto, setProducto] = useState<{ nombre: string; id: number | null }>({
    nombre: props.codigo.producto,
    id: props.codigo.producto_id,
  })
  const [precio, setPrecio] = useState(props.codigo.precio.toFixed(2))
  const [error, setError] = useState<string | null>(null)
  const refPrecio = useRef<HTMLInputElement>(null)
  useEffect(() => {
    requestAnimationFrame(() => refPrecio.current?.select())
  }, [])
  const guardar = async () => {
    try {
      await invoke('actualizar_codigo', { id: props.codigo.id, codigo, productoId: producto.id, producto: producto.nombre, precio })
      props.listo(true)
    } catch (e) {
      setError(String(e))
    }
  }
  const alTeclear = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      void guardar()
    }
  }
  return (
    <div className="caja__cobro">
      <p className="caja__cobro-total">Editar código de barras</p>
      <NexInput label="Código" autoComplete="off" value={codigo} onChange={(e) => (setCodigo(e.target.value), setError(null))} onKeyDown={alTeclear} />
      <BuscadorProducto nombre={producto.nombre} cambiar={(nombre, id) => (setProducto({ nombre, id }), setError(null))} />
      <NexInput
        ref={refPrecio}
        label="Precio de venta"
        inputMode="decimal"
        leading="$"
        autoComplete="off"
        value={precio}
        onChange={(e) => (setPrecio(e.target.value), setError(null))}
        onKeyDown={alTeclear}
      />
      <p className="caja__nota">Las etiquetas ya impresas no cambian: si cambia el código o el precio, vuelva a imprimirlas.</p>
      {error && (
        <p className="caja__aviso caja__aviso--danger" role="alert">
          {error}
        </p>
      )}
      <div className="caja__cobro-acciones">
        <NexButton appearance="filled" onClick={() => void guardar()}>
          Guardar (Intro)
        </NexButton>
        <NexButton appearance="ghost" onClick={() => props.listo(false)}>
          Regresar
        </NexButton>
      </div>
    </div>
  )
}
