// Administración de botones (solo desarrollador; como admin_botones de la v2, decidido el
// 2026-11-24): una fila por botón (orden, activo, etiqueta, acción) y una columna por usuario con
// la casilla de si lo ve. La plantilla (__default__) va primero: es lo que recibe un usuario nuevo
// la primera vez que abre la caja. Rust exige el permiso en cada cambio.

import { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { NexButton, NexInput, NexSelect } from '@nexfluid/react'

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
  const casilla = (etiqueta: string, marcada: boolean, cambio: (v: boolean) => void) => (
    <input type="checkbox" className="caja__casilla" aria-label={etiqueta} checked={marcada} onChange={(e) => cambio(e.target.checked)} />
  )

  return (
    <section className="caja__admin-botones" aria-label="Administrar botones">
      {error && (
        <p className="caja__aviso caja__aviso--danger" role="alert">
          {error}
        </p>
      )}
      <div className="caja__matriz">
        <table>
          <thead>
            <tr>
              <th className="caja__matriz-esquina">
                <span className="caja__nota">Clic en un botón para editarlo</span>
              </th>
              {botones.map((b) => (
                <th key={b.id} className="caja__matriz-boton" data-elegido={editor?.id === b.id ? '' : undefined} data-inactivo={b.activo ? undefined : ''}>
                  <button type="button" title={`${b.etiqueta} · ${b.accion}`} onClick={() => setEditor(editor?.id === b.id ? null : { id: b.id, etiqueta: b.etiqueta, accion: b.accion })}>
                    <span>{b.etiqueta}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="caja__matriz-activo">
              <th scope="row">Activo</th>
              {botones.map((b) => (
                <td key={b.id}>{casilla(`${b.etiqueta} activo`, b.activo, (v) => void cambiar('poner_activo', { boton: b.id, activo: v }))}</td>
              ))}
            </tr>
            {usuarios.map((u) => (
              <tr key={u.id}>
                <th scope="row" title={u.plantilla ? 'Plantilla: lo que recibe un usuario nuevo' : u.nombre}>
                  {u.plantilla ? 'DEFAULT' : u.nombre}
                </th>
                {botones.map((b) => (
                  <td key={b.id} data-inactivo={b.activo ? undefined : ''}>
                    {casilla(`${b.etiqueta} para ${u.plantilla ? 'la plantilla' : u.nombre}`, b.visible_para.includes(u.id), (v) =>
                      void cambiar('poner_visible', { boton: b.id, usuario: u.id, visible: v }),
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
