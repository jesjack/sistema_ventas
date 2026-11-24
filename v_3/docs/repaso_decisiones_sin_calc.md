# Repaso de D1–D23 sin LibreOffice Calc (2026-11-24)

El 2026-11-23 la V3 dejó Calc: ahora es una sola aplicación **Rust + Tauri** con la interfaz en un
webview (React + NexFluid), y `camera_viewer` sigue en Python como proceso hijo (ver
`CONTEXTO_SESION.md`). Este documento marca qué pasa con cada decisión de `mapa_v2.md` §4 y con
los pendientes de §5. No reescribe el mapa: el razonamiento original sigue ahí.

**Leyenda:** ✅ sigue igual · 🔄 sigue, adaptada · ❌ muere con Calc.

## Resumen

| D | Tema | Estado | En una línea |
|---|---|---|---|
| D1 | Enter y escáner | 🔄 | Se capturan en la ventana de la app (eventos del webview), no en Calc ni con `keyboard` |
| D2 | Lógica de negocio en App | 🔄 | En Rust (`dominio`/`servicios`); el webview solo pinta y captura |
| D3 | Clics: Basic + `.evt` | ❌ | Los botones son componentes de la interfaz |
| D4 | Prebake | ❌ | No hay documento `.ods` que cargar |
| D5 | App lanza a soffice y UNO | 🔄 | Un solo proceso (Tauri); solo lanza a `camera_viewer` |
| D6 | Foco Qt ↔ Calc | ❌ | Los diálogos son de la misma ventana |
| D7 | `main.ods` por usuario | ❌ | No hay `main.ods` |
| D8 | Instancias y turno en `ventas.db` | ✅ | Instancia única por usuario + token de turno |
| D9 | Sin rutas fijas | 🔄 | Sigue; se va la búsqueda de LibreOffice |
| D10 | ¿Quién decide si fue escaneo? | 🔄 | La app, con la hora real de cada tecla |
| D11 | Cámaras aparte e integradas con ventas | ✅ | Como la amplió D22 |
| D12 | admin_botones como diálogo Qt | 🔄 | Pantalla de la app; falta decidir el modelo de botones (P1) |
| D13 | Macros Basic | ❌ | No hay macros |
| D14 | Tab no se consume | 🔄 | El autocompletado es en línea (`NexCombobox`); muere `consumir_tab` |
| D15 | Cobro rápido sin ticket | ✅ | Regla de negocio |
| D16 | Instalación con `uv` | 🔄 | Instaladores de Tauri; `uv` solo si hace falta para `camera_viewer` (P4) |
| D17 | Teclas durante un diálogo | ✅ | Mismas reglas de diseño de los diálogos |
| D18 | Estructura del código (Qt, paquete Python) | 🔄 | Se va Qt y el paquete Python; quedan los principios |
| D19 | Grupo del sistema para los datos | ✅ | Igual |
| D20 | Ajustes de la tercera ronda | 🔄 | Sigue turno, hash del código y origen; mueren `.evt` y versión de LibreOffice |
| D21 | Papeles, permisos y apertura de caja | ✅ | Íntegra |
| D22 | App de larga vida, cámaras como hijo | 🔄 | "Reabrir LibreOffice" pasa a "traer la ventana al frente" |
| D23 | Detalles de la quinta ronda | 🔄 | "VER EN CÁMARAS" lee la fila seleccionada de la tabla de la app |

## Detalle de las que cambian

**D1. Enter y escáner.** El teclado se lee con los eventos del webview mientras la ventana de la
app tiene el foco: sin `keyboard`, sin root, sin chequeo de foco de Calc, igual en Linux y
Windows. **Cambio importante respecto a la medición de septiembre:** cada evento trae su hora
real (`KeyboardEvent.timeStamp`), sin el puente UNO que deformaba el ritmo. En la fase 0 el
escáner dio 16 ms/tecla y a mano 80–150 ms. El prototipo usa hoy "pausa máxima 35 ms, mínimo 4
caracteres" (`src/escaner.ts`); al pasar a producción conviene unificarla con la regla propuesta
en D1 (mínimo 3 caracteres antes del Enter, promedio ≤ 40 ms, reinicio con huecos > 100 ms) o
volver a las reglas por tecla de la V2, que con horas reales vuelven a servir. Se mantiene el
hallazgo del lector con distribución de EE. UU. (`SN:` → `SNÑ`): el webview recibe el carácter
ya traducido por el sistema. Pendiente: medir en Windows.

**D2. Lógica de negocio.** Toda en Rust: carrito, cobro, servicios de base de datos, permisos y
turno. El webview solo pinta y captura, y llama a comandos de Rust. Las reglas del carrito están
hoy duplicadas en `src/carrito.ts` (prototipo); en la fase 1 pasan a Rust con pruebas contra la
V2.

**D5. Quién lanza a quién.** La app Tauri es el único proceso de la caja. No hay soffice ni
proceso UNO. Lanza a `camera_viewer` como hijo (D22). El estado de arranque sigue en memoria.

**D9. Sin rutas fijas.** Sigue. En Rust, las rutas de datos salen de las rutas estándar de cada
sistema (crate `directories` o la API de rutas de Tauri). **El prototipo todavía viola D9:**
`lib.rs` busca la base en la carpeta del código (`CARGO_MANIFEST_DIR`); se corrige en la fase 1.

**D10. ¿Quién decide si fue escaneo?** La app, en el webview, que es donde está la hora real.
Rust recibe el código ya separado. La mejora futura de identificar el dispositivo (Raw Input en
Windows, `/dev/input` con `udev` en Linux) sigue igual de válida y sigue pospuesta.

**D12. admin_botones.** Pasa a ser una pantalla de la app. Lo que no está decidido es si se
conserva el modelo de la V2 (tabla `botones`, visibilidad por usuario, una acción por archivo):
ver P1.

**D14. Tab.** Sin Calc no hay celda B4 ni `XKeyHandler`. El autocompletado de producto es en
línea (`NexCombobox`): la lista se abre al escribir, Intro elige, y **Tab cierra la lista sin
elegir y pasa al siguiente campo** (nunca se consume, como pedía D14). El interruptor
`consumir_tab` deja de existir.

**D16. Instalación.** Los instaladores de Tauri (`.deb`/AppImage en Linux, `.msi` en Windows)
instalan para todo el equipo, como pedía D20. Ya no hay que instalar LibreOffice. El paso de
administrador (grupo del sistema, carpeta de datos compartida, acceso directo) sigue haciendo
falta. `camera_viewer` necesita su propio entorno de Python (PySide6, OpenCV): ver P4.

**D18. Estructura del código.** Se va lo de Qt (bucle, señales, `PySide6`) y el paquete Python
`src/sistema_ventas/`. Quedan los principios, traducidos:
- `dominio` y `servicios` sin dependencias de la interfaz, probables con `cargo test`.
- Nada lento en el hilo de la interfaz: los comandos de Tauri que imprimen, abren el cajón o
  esperan van asíncronos o en hilos, con tiempo máximo.
- Vigilante y tracebacks legibles para IA: `panic hook` de Rust y el log único.
- El canal con UNO muere; hace falta uno con `camera_viewer` (P3).
- Las acciones de los botones: depende de P1.

**D20.** Siguen: comprobar el turno cada ~3 s, el código de caja como hash (corregido por D21) y
publicar desde el repositorio con una etiqueta por versión (ahora como instaladores). Mueren: la
ruta de los `.evt` para Basic y la versión mínima de LibreOffice. El `log_actual` ya lo había
sustituido D22.

**D22.** Igual, salvo que el acceso directo con la app ya abierta **trae su ventana al frente**
(antes: "vuelve a abrir LibreOffice"), y la marca del log al reabrir LibreOffice ya no aplica.
Instancia única con el plugin `single-instance` de Tauri.

**D23.** Igual, salvo "VER EN CÁMARAS": se selecciona una fila de VENTAS REALIZADAS en la tabla
de la app (no en la hoja) y la app abre las cámaras a esa hora.

## Pendientes de `mapa_v2.md` §5

| # | Pendiente | Estado |
|---|---|---|
| 4 | D6: foco del diálogo de cobro Qt | ❌ No aplica (diálogos en la misma ventana) |
| 5 | D13: macros sin avisos | ❌ No aplica |
| 6 | D20: versión mínima de LibreOffice | ❌ No aplica |
| 7 | D1 en Windows y con el POS cargado | 🔄 Sigue: medir el teclado del webview en Windows |
| 8 | Instalador de `uv` en Linux | 🔄 Solo si `camera_viewer` lo usa (P4) |
| 9 | Enter se consume en UNO | ❌ No aplica |
| 10 | Conservar "¿venta en curso?" además de D17 | ✅ Sigue |
| 11 | El ticket abre el cajón; sin ticket, tarea propia | ✅ Sigue (D23 ya los registra a los dos) |
| 12 | Código de caja de la V2 (`7410`) público en GitHub | ✅ **Sigue pendiente en la V2**: cambiarlo |
| 13 | Lector con distribución de EE. UU. | ✅ Sigue (ver D1) |

## Preguntas nuevas que abre el cambio (respondidas el 2026-11-24)

- **P1. Botones configurables — DECIDIDO: siguen siendo configurables.** Se conserva el modelo de
  la v2 (tabla `botones`, visibilidad por usuario, pantalla de administración). Diferencia: las
  acciones van compiladas en el programa (Rust); lo configurable es qué botones aparecen, su
  etiqueta, su orden y quién los ve, eligiendo de la lista de acciones del programa. Una acción
  nueva requiere programarla y publicar una versión.
- **P2. NexSheets o tabla propia — A EVALUAR:** el usuario quiere ver NexSheets. Prueba pendiente
  en el prototipo (carrito o VENTAS REALIZADAS) para comparar.
- **P3/P4. Cámaras — DECIDIDO: se integran a la app, en Rust, en la misma interfaz.** Sustituye a
  "camera_viewer como proceso hijo en Python" (D22) y al canal JSON. Prueba de video y diseño del
  embudo al DVR: [`camaras_v3.md`](camaras_v3.md). Mientras tanto, `camera_viewer` sigue en la v2.
- **P5. Impresoras — DECIDIDO:** **solo Linux por ahora** (ticket ESC/POS escrito a
  `/dev/usb/lp0`, etiquetadora NIIMBOT por `/dev/ttyACM0`, ambas solo en Linux) y **se quedan las
  impresoras actuales**. En la fase 3 se porta lo que ya existe; la NIIMBOT (protocolo no
  estándar) es lo más costoso. Windows pasa a segundo plano, sin atarse a Linux donde no cueste.
