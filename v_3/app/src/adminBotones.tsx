// Administración de botones (solo desarrollador; como admin_botones de la v2, decidido el
// 2026-11-24): una fila por botón (orden, activo, etiqueta, acción) y una columna por usuario con
// la casilla de si lo ve. La plantilla (__default__) va primero: es lo que recibe un usuario nuevo
// la primera vez que abre la caja. Rust exige el permiso en cada cambio.

import { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { NexButton, NexCheckbox, NexInput, NexSelect } from '@nexfluid/react'
import { Icono } from './iconos.tsx'

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
  const [nuevo, setNuevo] = useState({ etiqueta: '', accion: 'cobrar_carrito' })
  const [etiquetas, setEtiquetas] = useState<Record<number, string>>({})

  const leer = () =>
    invoke<{ botones: BotonAdmin[]; usuarios: UsuarioBotones[] }>('botones_admin').then(
      (m) => {
        setBotones(m.botones)
        setUsuarios(m.usuarios)
        setEtiquetas(Object.fromEntries(m.botones.map((b) => [b.id, b.etiqueta])))
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
    } catch (e) {
      setError(String(e))
    }
  }
  const mover = (indice: number, delta: number) => {
    const ids = botones.map((b) => b.id)
    const destino = indice + delta
    if (destino < 0 || destino >= ids.length) return
    ;[ids[indice], ids[destino]] = [ids[destino]!, ids[indice]!]
    void cambiar('ordenar_botones', { ids })
  }
  const guardarEtiqueta = (b: BotonAdmin) => {
    const etiqueta = (etiquetas[b.id] ?? '').trim()
    if (etiqueta && etiqueta !== b.etiqueta) void cambiar('editar_boton', { boton: b.id, etiqueta, accion: b.accion })
    else setEtiquetas((e) => ({ ...e, [b.id]: b.etiqueta }))
  }

  return (
    <section className="caja__admin-botones" aria-label="Administrar botones">
      <p className="caja__nota">
        Qué botones hay, en qué orden y quién ve cada uno. <strong>DEFAULT</strong> es la plantilla: lo que recibe un usuario nuevo la
        primera vez que abre la caja (después, sus botones son suyos). Los cambios se guardan al momento.
      </p>
      {error && (
        <p className="caja__aviso caja__aviso--danger" role="alert">
          {error}
        </p>
      )}
      <div className="caja__tabla-codigos caja__tabla-botones">
        <table>
          <thead>
            <tr>
              <th aria-label="Orden" />
              <th>Activo</th>
              <th>Etiqueta</th>
              <th>Acción</th>
              {usuarios.map((u) => (
                <th key={u.id} className="caja__th-usuario" title={u.nombre}>
                  <span>{u.plantilla ? 'DEFAULT' : u.nombre}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {botones.map((b, i) => (
              <tr key={b.id} data-inactivo={b.activo ? undefined : ''}>
                <td className="caja__orden">
                  <NexButton appearance="ghost" density="compact" aria-label="Subir" disabled={i === 0} onClick={() => mover(i, -1)}>
                    ↑
                  </NexButton>
                  <NexButton appearance="ghost" density="compact" aria-label="Bajar" disabled={i === botones.length - 1} onClick={() => mover(i, 1)}>
                    ↓
                  </NexButton>
                </td>
                <td>
                  <NexCheckbox label="Activo" className="caja__casilla-sola" checked={b.activo} onChange={(e) => void cambiar('poner_activo', { boton: b.id, activo: e.target.checked })} />
                </td>
                <td>
                  <div className="caja__etiqueta-boton">
                    <Icono nombre={b.accion} />
                    <NexInput
                      label="Etiqueta"
                      hideLabel
                      density="compact"
                      autoComplete="off"
                      value={etiquetas[b.id] ?? b.etiqueta}
                      onChange={(e) => setEtiquetas((x) => ({ ...x, [b.id]: e.target.value }))}
                      onBlur={() => guardarEtiqueta(b)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                        else if (e.key === 'Escape') setEtiquetas((x) => ({ ...x, [b.id]: b.etiqueta }))
                      }}
                    />
                  </div>
                </td>
                <td>
                  <NexSelect
                    label="Acción"
                    hideLabel
                    density="compact"
                    value={b.accion}
                    options={opcionesDe(b.accion)}
                    onValueChange={(accion) => void cambiar('editar_boton', { boton: b.id, etiqueta: b.etiqueta, accion })}
                  />
                </td>
                {usuarios.map((u) => (
                  <td key={u.id} className="caja__celda-casilla">
                    <NexCheckbox
                      label={`${b.etiqueta} para ${u.plantilla ? 'la plantilla' : u.nombre}`}
                      className="caja__casilla-sola"
                      checked={b.visible_para.includes(u.id)}
                      onChange={(e) => void cambiar('poner_visible', { boton: b.id, usuario: u.id, visible: e.target.checked })}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="caja__crear-boton">
        <NexInput
          label="Botón nuevo"
          placeholder="Etiqueta (p. ej. COBRAR)"
          density="compact"
          autoComplete="off"
          value={nuevo.etiqueta}
          onChange={(e) => setNuevo({ ...nuevo, etiqueta: e.target.value })}
        />
        <NexSelect
          label="Acción"
          density="compact"
          value={nuevo.accion}
          options={opcionesDe(nuevo.accion)}
          onValueChange={(accion) => setNuevo({ ...nuevo, accion })}
        />
        <NexButton
          appearance="filled"
          onClick={() =>
            void cambiar('crear_boton', { etiqueta: nuevo.etiqueta, accion: nuevo.accion }).then(() => setNuevo({ etiqueta: '', accion: nuevo.accion }))
          }
        >
          Crear botón
        </NexButton>
      </div>
      <p className="caja__nota">Un botón nuevo queda al final, activo y visible para la plantilla; marca a quién más se le muestra.</p>
    </section>
  )
}
