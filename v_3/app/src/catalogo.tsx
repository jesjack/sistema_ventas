// AUTOCOMPLETADO: el catálogo de productos (como la v2: agregar, cambiar el nombre, eliminar si no
// tiene códigos) con el corrector ortográfico (`nucleo::corrector`): sugiere mientras se escribe,
// recuerda las palabras corregidas a mano y "Revisar ortografía" lista todo el catálogo.
// El catálogo guarda los nombres en minúsculas; aquí se muestran con formato ("Blusa Básica").

import { useEffect, useMemo, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { NexButton, NexCheckbox, NexInput, NexSegmented } from '@nexfluid/react'

interface ProductoCatalogo {
  id: number
  nombre: string
  codigos: number
}
interface Sugerencia {
  producto_id: number
  producto: string
  sugerencia: string
  ya_existe_id: number | null
}
interface Correccion {
  incorrecta: string
  correcta: string
}
type Cambio = { resultado: 'Hecho'; id: number } | { resultado: 'YaExiste'; id: number; nombre: string }

/** Las mismas preposiciones que `nucleo::catalogo::PREPOSICIONES`. */
const PREPOSICIONES = new Set(['de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'unos', 'unas', 'y', 'o'])

/** "mayon de faja" → "Mayon de Faja" (como `nucleo::catalogo::formatear_nombre`). */
export function formatearNombre(texto: string): string {
  return texto
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => {
      const m = p.toLowerCase()
      return PREPOSICIONES.has(m) ? m : m.charAt(0).toUpperCase() + m.slice(1)
    })
    .join(' ')
}

const sinAcentos = (t: string) => t.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()

/** La sugerencia del corrector para lo escrito (se pide a Rust al dejar de escribir). */
function useSugerencia(nombre: string): string | null {
  const [sugerencia, setSugerencia] = useState<string | null>(null)
  useEffect(() => {
    if (!nombre.trim()) {
      setSugerencia(null)
      return
    }
    let vigente = true
    const id = setTimeout(() => {
      invoke<string | null>('sugerir_nombre', { nombre }).then((s) => vigente && setSugerencia(s), () => {})
    }, 200)
    return () => {
      vigente = false
      clearTimeout(id)
    }
  }, [nombre])
  return sugerencia
}

/** "¿Quisiste decir «…»?" con su botón. */
export function AvisoSugerencia(props: { nombre: string; usar: (s: string) => void }) {
  const sugerencia = useSugerencia(props.nombre)
  if (!sugerencia) return null
  return (
    <p className="caja__sugerencia" role="status">
      ¿Quisiste decir «{formatearNombre(sugerencia)}»?{' '}
      <NexButton appearance="ghost" density="compact" onClick={() => props.usar(sugerencia)}>
        Usar sugerencia
      </NexButton>
    </p>
  )
}

export function PanelCatalogo(props: { cerrar: () => void }) {
  const [vista, setVista] = useState<'productos' | 'revisar'>('productos')
  const [productos, setProductos] = useState<ProductoCatalogo[]>([])
  const [revision, setRevision] = useState<Sugerencia[]>([])
  const [correcciones, setCorrecciones] = useState<Correccion[]>([])
  const [filtro, setFiltro] = useState('')
  const [elegido, setElegido] = useState<ProductoCatalogo | null>(null)
  const [nombre, setNombre] = useState('')
  const [recordar, setRecordar] = useState(true)
  const [aviso, setAviso] = useState<{ texto: string; unir?: { origen: number; destino: number; nombre: string } } | null>(null)
  const refNombre = useRef<HTMLInputElement>(null)

  const leer = async () => {
    const [p, r, c] = await Promise.all([
      invoke<ProductoCatalogo[]>('catalogo'),
      invoke<Sugerencia[]>('revisar_catalogo'),
      invoke<Correccion[]>('correcciones'),
    ])
    setProductos(p)
    setRevision(r)
    setCorrecciones(c)
    return p
  }
  useEffect(() => {
    void leer().catch((e) => setAviso({ texto: String(e) }))
    requestAnimationFrame(() => refNombre.current?.focus())
  }, [])

  const visibles = useMemo(() => {
    const f = sinAcentos(filtro.trim())
    return f ? productos.filter((p) => sinAcentos(p.nombre).includes(f)) : productos
  }, [productos, filtro])

  const elegir = (p: ProductoCatalogo | null) => {
    setElegido(p)
    setNombre(p ? formatearNombre(p.nombre) : '')
    setAviso(null)
  }
  const despues = async (cambio: Cambio, hecho: string, origen: number | null) => {
    if (cambio.resultado === 'YaExiste') {
      setAviso({
        texto: `Ya existe «${formatearNombre(cambio.nombre)}».`,
        unir: origen !== null ? { origen, destino: cambio.id, nombre: cambio.nombre } : undefined,
      })
      return
    }
    const lista = await leer()
    elegir(lista.find((p) => p.id === cambio.id) ?? null)
    setAviso({ texto: hecho })
  }
  const agregar = async () => {
    if (!nombre.trim()) return setAviso({ texto: 'Escribe un nombre de producto.' })
    try {
      await despues(await invoke<Cambio>('agregar_producto', { nombre }), 'Producto agregado.', null)
    } catch (e) {
      setAviso({ texto: String(e) })
    }
  }
  const renombrar = async (id: number, nuevo: string, conRecordar: boolean) => {
    if (!nuevo.trim()) return setAviso({ texto: 'Escribe el nuevo nombre del producto.' })
    try {
      await despues(await invoke<Cambio>('renombrar_producto', { id, nombre: nuevo, recordar: conRecordar }), 'Producto actualizado.', id)
    } catch (e) {
      setAviso({ texto: String(e) })
    }
  }
  const unir = async (origen: number, destino: number, nombreDestino: string) => {
    try {
      await invoke('unir_productos', { origen, destino })
      const lista = await leer()
      elegir(lista.find((p) => p.id === destino) ?? null)
      setAviso({ texto: `Productos unidos en «${formatearNombre(nombreDestino)}»: sus códigos de barras pasaron a este.` })
    } catch (e) {
      setAviso({ texto: String(e) })
    }
  }
  const eliminar = async () => {
    if (!elegido) return
    try {
      await invoke('eliminar_producto', { id: elegido.id })
      await leer()
      setAviso({ texto: `Producto eliminado: ${formatearNombre(elegido.nombre)}` })
      elegir(null)
    } catch (e) {
      setAviso({ texto: String(e) })
    }
  }

  const cambiaNombre = elegido !== null && nombre.trim().toLowerCase() !== elegido.nombre.toLowerCase()

  return (
    <div className="caja__cobro">
      <div className="caja__catalogo-cabecera">
        <p className="caja__cobro-total">Productos para autocompletado</p>
        <NexSegmented
          aria-label="Catálogo"
          density="compact"
          value={vista}
          onValueChange={(v) => setVista(v as 'productos' | 'revisar')}
          options={[
            { value: 'productos', label: `Productos (${productos.length})` },
            { value: 'revisar', label: `Revisar ortografía (${revision.length})` },
          ]}
        />
      </div>

      {vista === 'productos' ? (
        <>
          <NexInput label="Buscar" hideLabel placeholder="Buscar en el catálogo" autoComplete="off" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
          <ul className="caja__catalogo-lista" role="listbox" aria-label="Productos">
            {visibles.map((p) => (
              <li
                key={p.id}
                role="option"
                aria-selected={elegido?.id === p.id}
                className="caja__catalogo-item"
                onClick={() => elegir(elegido?.id === p.id ? null : p)}
              >
                <span>{formatearNombre(p.nombre)}</span>
                {p.codigos > 0 && <span className="caja__nota">{p.codigos} código{p.codigos === 1 ? '' : 's'}</span>}
              </li>
            ))}
            {visibles.length === 0 && <li className="caja__nota">{productos.length ? 'Ningún producto coincide.' : 'Catálogo vacío. Agrega tu primer producto.'}</li>}
          </ul>
          <NexInput
            ref={refNombre}
            label={elegido ? `Nombre de «${formatearNombre(elegido.nombre)}»` : 'Producto nuevo'}
            description={elegido ? 'Intro guarda el cambio · clic en el producto de nuevo para soltarlo' : 'Intro lo agrega al catálogo'}
            autoComplete="off"
            value={nombre}
            onChange={(e) => {
              setNombre(e.target.value)
              setAviso(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void (elegido ? renombrar(elegido.id, nombre, recordar) : agregar())
              }
            }}
          />
          <AvisoSugerencia nombre={nombre} usar={(s) => setNombre(formatearNombre(s))} />
          {cambiaNombre && (
            <NexCheckbox
              label="Recordar esta corrección"
              description="Si cambiaste una palabra mal escrita (p. ej. «bycker» → «biker»), se sugerirá la próxima vez."
              checked={recordar}
              onChange={(e) => setRecordar(e.target.checked)}
            />
          )}
          {aviso && (
            <p className="caja__aviso caja__aviso--neutral" role="status">
              {aviso.texto}{' '}
              {aviso.unir && (
                <NexButton appearance="outlined" density="compact" onClick={() => void unir(aviso.unir!.origen, aviso.unir!.destino, aviso.unir!.nombre)}>
                  Unir con ese producto
                </NexButton>
              )}
            </p>
          )}
          <div className="caja__cobro-acciones">
            {elegido ? (
              <>
                <NexButton appearance="filled" disabled={!cambiaNombre} onClick={() => void renombrar(elegido.id, nombre, recordar)}>
                  Guardar cambio (Intro)
                </NexButton>
                <NexButton
                  appearance="outlined"
                  tone="danger"
                  disabled={elegido.codigos > 0}
                  title={elegido.codigos > 0 ? 'No se puede eliminar: tiene códigos de barras registrados.' : undefined}
                  onClick={() => void eliminar()}
                >
                  Eliminar
                </NexButton>
              </>
            ) : (
              <NexButton appearance="filled" onClick={() => void agregar()}>
                Agregar (Intro)
              </NexButton>
            )}
            <NexButton appearance="ghost" onClick={props.cerrar}>
              Cerrar
            </NexButton>
          </div>
        </>
      ) : (
        <>
          <p className="caja__nota">
            Productos con una posible falta de ortografía. Si la forma correcta ya es otro producto, se pueden unir: los códigos de
            barras pasan a ese producto (las ventas ya hechas no cambian).
          </p>
          <ul className="caja__catalogo-lista">
            {revision.map((s) => (
              <li key={s.producto_id} className="caja__catalogo-item">
                <span>
                  {formatearNombre(s.producto)} → <strong>{formatearNombre(s.sugerencia)}</strong>
                </span>
                {s.ya_existe_id !== null ? (
                  <NexButton appearance="outlined" density="compact" onClick={() => void unir(s.producto_id, s.ya_existe_id!, s.sugerencia)}>
                    Unir
                  </NexButton>
                ) : (
                  <NexButton appearance="outlined" density="compact" onClick={() => void renombrar(s.producto_id, s.sugerencia, false)}>
                    Corregir
                  </NexButton>
                )}
              </li>
            ))}
            {revision.length === 0 && <li className="caja__nota">No hay nada que corregir.</li>}
          </ul>
          {aviso && <p className="caja__nota">{aviso.texto}</p>}
          <p className="caja__corte-titulo">Correcciones recordadas</p>
          <ul className="caja__catalogo-lista caja__catalogo-lista--corta">
            {correcciones.map((c) => (
              <li key={c.incorrecta} className="caja__catalogo-item">
                <span>
                  {c.incorrecta} → <strong>{c.correcta}</strong>
                </span>
                <NexButton
                  appearance="ghost"
                  density="compact"
                  onClick={() => void invoke('olvidar_correccion', { incorrecta: c.incorrecta }).then(() => leer())}
                >
                  Olvidar
                </NexButton>
              </li>
            ))}
            {correcciones.length === 0 && <li className="caja__nota">Ninguna todavía: se aprenden al corregir un nombre a mano.</li>}
          </ul>
          <div className="caja__cobro-acciones">
            <NexButton appearance="ghost" onClick={props.cerrar}>
              Cerrar
            </NexButton>
          </div>
        </>
      )}
    </div>
  )
}
