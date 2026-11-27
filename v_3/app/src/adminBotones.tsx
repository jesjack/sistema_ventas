// Administración de botones (solo desarrollador; como admin_botones de la v2, decidido el
// 2026-11-24): una fila por botón (orden, activo, etiqueta, acción) y una columna por usuario con
// la casilla de si lo ve. La plantilla (__default__) va primero: es lo que recibe un usuario nuevo
// la primera vez que abre la caja. Rust exige el permiso en cada cambio.

import { useEffect, useMemo, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { NexButton, NexInput, NexSelect } from '@nexfluid/react'
import { NexSheets, cellKey, createSheet, createWorkbook, type Sheet, type Workbook } from '@nexfluid/react/sheets'
import { ALTO_FILA_HOJA, medidorDeTexto } from './hojas.ts'
import { useMarcoHoja } from './marcoHoja.ts'

interface BotonAdmin {
  id: number
  etiqueta: string
  accion: string
  orden: number
  activo: boolean
  visible_para: number[]
}
interface UsuarioBotones {
  id: number
  nombre: string
  plantilla: boolean
}

/** Las acciones que la caja sabe hacer (las de `accion()` en App.tsx), con su estado en la v3. */
const ACCIONES: { valor: string; texto: string }[] = [
  { valor: 'cobrar_carrito', texto: 'Cobrar carrito' },
  { valor: 'limpiar_carrito', texto: 'Limpiar carrito' },
  { valor: 'abrir_caja', texto: 'Abrir caja' },
  { valor: 'corte_de_caja', texto: 'Corte de caja' },
  { valor: 'autocompletado', texto: 'Catálogo (autocompletado)' },
  { valor: 'ver_codigos_de_barras', texto: 'Ver códigos de barras' },
  { valor: 'ver_ventas', texto: 'Ver ventas (cambia de pantalla)' },
  { valor: 'imprimir_varios_codigos', texto: 'Imprimir códigos (fase 3)' },
  { valor: 'imprimir_codigo_de_barras', texto: 'Imprimir un código (fase 3)' },
  { valor: 'ver_camaras', texto: 'Ver cámaras (fase 5)' },
  { valor: 'ping', texto: 'Ping (prueba)' },
]

const opcionesDe = (actual: string) =>
  (ACCIONES.some((a) => a.valor === actual) ? ACCIONES : [...ACCIONES, { valor: actual, texto: `${actual} (desconocida)` }]).map((a) => ({
    value: a.valor,
    label: a.texto,
  }))

export function PanelBotones(props: { alCambiar: () => void }) {
  const [botones, setBotones] = useState<BotonAdmin[]>([])
  const [usuarios, setUsuarios] = useState<UsuarioBotones[]>([])
  const [error, setError] = useState<string | null>(null)
  // El panel de abajo: editar un botón (clic en su encabezado) o crear uno.
  const [editor, setEditor] = useState<{ id: number | null; etiqueta: string; accion: string } | null>(null)

  const leer = () =>
    invoke<{ botones: BotonAdmin[]; usuarios: UsuarioBotones[] }>('botones_admin').then(
      (m) => {
        setBotones(m.botones)
        setUsuarios(m.usuarios)
        setError(null)
      },
      (e) => setError(String(e)),
    )
  useEffect(() => void leer(), [])

  /** Un cambio: se guarda en Rust, se relee la matriz y se avisa a la columna de botones. */
  const cambiar = async (comando: string, args: Record<string, unknown>) => {
    try {
      await invoke(comando, args)
      await leer()
      props.alCambiar()
      return true
    } catch (e) {
      setError(String(e))
      return false
    }
  }
  const mover = (id: number, delta: number) => {
    const ids = botones.map((b) => b.id)
    const i = ids.indexOf(id)
    const j = i + delta
    if (i < 0 || j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j]!, ids[i]!]
    void cambiar('ordenar_botones', { ids })
  }
  const guardarEditor = async () => {
    if (!editor) return
    const ok = editor.id === null
      ? await cambiar('crear_boton', { etiqueta: editor.etiqueta, accion: editor.accion })
      : await cambiar('editar_boton', { boton: editor.id, etiqueta: editor.etiqueta, accion: editor.accion })
    if (ok) setEditor(null)
  }
  const indiceEditado = editor?.id != null ? botones.findIndex((b) => b.id === editor.id) : -1

  // ---- La hoja: filas = Activo + usuarios (sus nombres en lugar de números, `rowLabels`);
  // columnas = un botón cada una (30 × 30, nombre en vertical).
  const refHoja = useRef<HTMLDivElement>(null)
  // Lo que ocupa la hoja aparte de las celdas, MEDIDO (como el carrito): sin sumar px a ojo, que
  // dejaban un hueco abajo y a la derecha.
  const marco = useMarcoHoja(refHoja, [botones.length > 0])
  const filas = useMemo(
    () => [{ nombre: 'Activo', id: null as number | null }, ...usuarios.map((u) => ({ nombre: u.plantilla ? 'DEFAULT' : u.nombre, id: u.id as number | null }))],
    [usuarios],
  )
  const medir = (texto: string, encabezado = false) => (refHoja.current ? medidorDeTexto(refHoja.current)(texto, encabezado) : texto.length * 8)
  const anchoNombre = Math.ceil(Math.min(240, Math.max(90, ...filas.map((f) => medir(f.nombre) + 24))))
  const altoEncabezado = Math.ceil(Math.min(190, Math.max(60, ...botones.map((b) => medir(b.etiqueta, true) + 16))))
  const libro = useMemo<Workbook>(() => {
    const celdas: Sheet['cells'] = {}
    filas.forEach((f, r) => {
      botones.forEach((b, c) => {
        const marcada = f.id === null ? b.activo : b.visible_para.includes(f.id)
        if (marcada) celdas[cellKey(r, c)] = { input: '✓' }
      })
    })
    const hoja: Sheet = {
      ...createSheet('Botones', { rows: filas.length, columns: Math.max(botones.length, 1), cells: celdas, headers: botones.map((b) => b.etiqueta) }, 'botones'),
      columnWidths: Object.fromEntries(botones.map((_, c) => [c, ALTO_FILA_HOJA])),
    }
    return createWorkbook([hoja])
  }, [filas, botones])

  /** Cambia la casilla de la fila `r` y la columna `c`. */
  const alternar = (r: number, c: number) => {
    const b = botones[c]
    const f = filas[r]
    if (!b || !f) return
    if (f.id === null) void cambiar('poner_activo', { boton: b.id, activo: !b.activo })
    else void cambiar('poner_visible', { boton: b.id, usuario: f.id, visible: !b.visible_para.includes(f.id) })
  }
  const alClic = (e: React.MouseEvent) => {
    const el = e.target as HTMLElement
    const cabeza = el.closest<HTMLElement>('[role="columnheader"]')
    if (cabeza) {
      const b = botones[Number(cabeza.getAttribute('aria-colindex')) - 2]
      if (b) setEditor(editor?.id === b.id ? null : { id: b.id, etiqueta: b.etiqueta, accion: b.accion })
      return
    }
    const celda = el.closest<HTMLElement>('[role="gridcell"]')
    const fila = celda?.closest<HTMLElement>('[role="row"]')
    if (celda && fila) alternar(Number(fila.getAttribute('aria-rowindex')) - 2, Number(celda.getAttribute('aria-colindex')) - 2)
  }
  // Espacio sobre la celda activa (la marca la rejilla con aria-activedescendant: …-fila-columna).
  const alTeclear = (e: React.KeyboardEvent) => {
    if (e.key !== ' ') return
    const activa = (e.target as HTMLElement).getAttribute('aria-activedescendant')?.match(/-(\d+)-(\d+)$/)
    if (!activa) return
    e.preventDefault()
    alternar(Number(activa[1]), Number(activa[2]))
  }
  // Columnas de botones inactivos, atenuadas (la hoja no tiene estilos por columna).
  const estiloInactivos = botones
    .map((b, c) => (b.activo ? null : `.caja__hoja--botones [aria-colindex="${c + 2}"]{opacity:.45}`))
    .filter(Boolean)
    .join('')

  return (
    <section className="caja__admin-botones" aria-label="Administrar botones">
      {error && (
        <p className="caja__aviso caja__aviso--danger" role="alert">
          {error}
        </p>
      )}
      {estiloInactivos && <style>{estiloInactivos}</style>}
      <div
        ref={refHoja}
        className="caja__marco-botones"
        style={{ width: `min(100%, ${anchoNombre + botones.length * ALTO_FILA_HOJA}px)` }}
        onClick={alClic}
        onKeyDown={alTeclear}
      >
        <NexSheets
          className="caja__hoja caja__hoja--botones"
          workbook={libro}
          readOnly
          extent={false}
          height={altoEncabezado + filas.length * ALTO_FILA_HOJA + marco.extraAlto}
          label="Botones por usuario"
          columnLabels="name"
          headerHeight={altoEncabezado}
          headerOrientation="vertical"
          rowLabels={filas.map((f) => f.nombre)}
          rowHeaderWidth={anchoNombre}
          tabs={false}
          statusBar={false}
          toolbar={false}
          formulaBar={false}
        />
      </div>
      <span className="caja__nota">Clic en una casilla (o Espacio) la cambia · clic en el nombre de un botón para editarlo.</span>

      {editor ? (
        <div className="caja__editor-boton">
          <NexInput
            label={editor.id === null ? 'Botón nuevo' : 'Etiqueta'}
            density="compact"
            autoComplete="off"
            autoFocus
            value={editor.etiqueta}
            onChange={(e) => setEditor({ ...editor, etiqueta: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void guardarEditor()
              else if (e.key === 'Escape') setEditor(null)
            }}
          />
          <NexSelect label="Acción" density="compact" value={editor.accion} options={opcionesDe(editor.accion)} onValueChange={(accion) => setEditor({ ...editor, accion })} />
          <div className="caja__cobro-acciones">
            {editor.id !== null && (
              <>
                <NexButton appearance="ghost" density="compact" disabled={indiceEditado <= 0} onClick={() => mover(editor.id!, -1)}>
                  ← Mover
                </NexButton>
                <NexButton appearance="ghost" density="compact" disabled={indiceEditado < 0 || indiceEditado >= botones.length - 1} onClick={() => mover(editor.id!, 1)}>
                  Mover →
                </NexButton>
              </>
            )}
            <NexButton appearance="filled" density="compact" onClick={() => void guardarEditor()}>
              {editor.id === null ? 'Crear' : 'Guardar'} (Intro)
            </NexButton>
            <NexButton appearance="ghost" density="compact" onClick={() => setEditor(null)}>
              Cerrar
            </NexButton>
          </div>
        </div>
      ) : (
        <div className="caja__cobro-acciones">
          <NexButton appearance="outlined" density="compact" onClick={() => setEditor({ id: null, etiqueta: '', accion: 'cobrar_carrito' })}>
            Crear botón
          </NexButton>
          <span className="caja__nota">DEFAULT es la plantilla: lo que recibe un usuario nuevo la primera vez que abre la caja.</span>
        </div>
      )}
    </section>
  )
}
