# Contexto para continuar la V3 (Rust + Tauri + NexFluid)

Documento de traspaso entre sesiones de trabajo (con o sin Claude). **Léelo antes de seguir.**
Última actualización: 2026-11-24, noche (**fase 1 completa**; ver §8; siguiente: fase 2).

## 1. La decisión de fondo

El diseño V3 original (`docs/mapa_v2.md`, `docs/diagrama_*`, decisiones D1–D23) seguía usando
LibreOffice Calc como interfaz, con dos intérpretes (UNO y venv) y un socket. **El 2026-11-23 se
decidió dejar Calc** y rehacer la caja con:

- **Rust + Tauri 2**: la lógica (SQLite, impresoras, cajón, permisos) en Rust; la interfaz en un
  webview (WebKitGTK en Linux, WebView2 en Windows).
- **React 19 + NexFluid** (la librería de interfaz de Chris, `gibran564/nexfluid`, MIT) para la
  interfaz.
- **Las cámaras se integran a la app, en Rust** (decisión del 2026-11-24, P3/P4): un solo programa
  y una sola interfaz. Mientras tanto `camera_viewer` (Python) sigue en la v2. Ver
  `camaras_v3.md`. YOLO no se usa (solo `cameras/test_ia.py`, un experimento).
- **Solo Linux por ahora** (P5) y se quedan las impresoras actuales (ticket ESC/POS, NIIMBOT).

Consecuencia (detalle en `repaso_decisiones_sin_calc.md`): muchas decisiones D1–D23 eran sobre Calc/UNO/Basic y **ya no aplican** (dos
intérpretes, socket, botones en Basic, `consumir_tab`, foco de Calc, hook global de teclado con
root, prehorneado). Las reglas de negocio **sí siguen**: roles y permisos (D21), reglas del cajón
y del código de un solo uso (D21/D23), App de larga vida con camera_viewer como hijo (D22), log
único por día.

La v2 (`~/sistema_ventas`, rama `v2`) **sigue en producción** en la PC de la caja hasta que la v3
haga todo lo que hace la v2.

## 2. Plan por fases

| Fase | Qué | Estado |
|---|---|---|
| 0 | Prototipo: Tauri + NexFluid en la PC de la caja, medir | **Hecha** (2026-11-24, también en release) |
| 1 | Núcleo en Rust: reglas de la v2 probadas contra ella, base propia de la v3 con importación, turno y permisos | **Hecha** (2026-11-24, §8) |
| 2 | Pantalla de venta completa (captura, carrito, cobro, VENTAS REALIZADAS), en paralelo con la v2 sobre una copia | |
| 3 | Hardware: ticket, cajón (reglas D21/D23), etiquetas | |
| 4 | Administración: usuarios, roles, turnos, botones | |
| 5 | Cámaras en Rust dentro de la app: embudo al DVR, vivo, grabaciones, "VER EN CÁMARAS" (ver `camaras_v3.md`) | Video probado (2026-11-24) |
| 6 | Instaladores de Tauri (.deb) con sus dependencias (`gstreamer1.0-plugins-bad`, VA-API) | `.deb` probado |

## 3. Resultados de la fase 0 (PC de la caja: 4 núcleos, 7.6 GB, Intel HD 630, Zorin OS 17, Wayland)

- Tecla → pantalla: mediana **19 ms**, p95 27 ms (modo desarrollo, sin optimizar).
- Consulta a Rust (autocompletado): mediana **2 ms**.
- Escáner: **16 ms/tecla** contra 80–150 ms de una persona: se distingue sin hook global.
- WebKitGTK 2.50.4 funciona; tuvo varias diferencias con Chromium que se corrigieron en NexFluid.
- **Release** (2026-11-24): compila en 5 min 22 s (2 núcleos, prioridad mínima); `.deb` de
  **3.95 MB**; ejecutable de 13 MB; memoria ~406 MB (app 154 + motor web 205 + red 47) contra
  ~337 MB de la v2 (LibreOffice 290 + Python 45, que además corre con `sudo`). Consulta a Rust 2 ms;
  escáner 16 ms/tecla. La medición "tecla → pantalla" **no es válida**: compara la hora del evento
  con `performance.now()`, que en WebKitGTK vienen de relojes distintos (dio −3 ms); corregirla
  midiendo con un solo reloj si se necesita el número. El ejecutable lleva la ruta de la base de
  esta PC (viola D9, se corrige en la fase 1).
- **Video de las cámaras** (2026-11-24): las 4 cámaras en vivo se ven en la vista web con ~18 % de
  un núcleo (la v2 gasta 15.5 %). Detalle y pendientes en `camaras_v3.md`.

## 4. El prototipo: `v_3/app/`

```
v_3/app/
  src/App.tsx          pantalla de venta + panel de mediciones y de pruebas de NexFluid
  src/carrito.ts       reglas del carrito (iguales a v_2/table_modules/carrito.py)
  src/escaner.ts       detector de escáner por ritmo (ignora Shift: hay códigos con mayúsculas y espacios)
  src/medicion.ts      mediciones tecla→pantalla y consultas
  src/depurarGota.ts   depurador: rastro verde del borde de la gota de NexFluid (solo desarrollo)
  src-tauri/src/lib.rs comandos Rust: buscar_productos, buscar_codigo, info_base (SQLite SOLO LECTURA)
  scripts/             crear_base_demo.py · copiar_base_real.py
  vendor/              NexFluid empaquetado (.tgz) desde la rama jesjack/feat/caja-v3
  datos/               ventas_copia.db (en .gitignore: el repo es PÚBLICO y tiene ventas reales)
```

Flujo de teclado (como la v2): Enter en Producto pasa a Precio (o elige la sugerencia); Enter en
Precio/Cantidad agrega (suma cantidades si producto y precio coinciden); Enter con Producto vacío
cobra; el escáner funciona en cualquier campo. El cobro es **simulado**: nada se guarda.

### Arrancar en otra PC

1. Requisitos (Linux): Node ≥ 22, Rust (`rustup`), y para Tauri:
   `sudo apt install libwebkit2gtk-4.1-dev libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev pkg-config`.
   En Windows: Rust con MSVC (Build Tools de Visual Studio) y WebView2 (ya viene en Windows 10/11).
2. Base de datos: en la caja `python3 -I scripts/copiar_base_real.py`; fuera de la caja
   `python3 scripts/crear_base_demo.py` (productos inventados). Otra ruta: variable `CAJA_DB`.
   Sin base, la app no arranca (`panic` en `lib.rs`).
3. `cd v_3/app && npm install && npm run tauri dev`.
4. En la PC de la caja, compilar con prioridad baja para no frenar la v2:
   `CARGO_BUILD_JOBS=2 nice -n 10 npm run tauri dev`. La primera compilación tarda varios
   minutos; evitarla en horario de venta (el detector de escáner de la v2 se basa en el ritmo y
   la CPU saturada lo puede confundir).

## 5. NexFluid: ramas y cómo llega a la caja

Clon en `~/nexfluid` (en la PC de la caja). El usuario tiene permiso de escritura en
`gibran564/nexfluid`. Convención de ramas del usuario: `jesjack/<tipo>/<nombre>`.

```
main (Chris)
 └─ jesjack/fix/nexinput-nexselect-webkit   solo errores (aceptables sin lo demás)
     └─ jesjack/feat/sugerencias-caja-v3    reporte, NexCombobox, propuestas opcionales
         └─ jesjack/feat/caja-v3            la que usa la caja (hoy = sugerencias)
```

Las tres están en GitHub. **El diseño es de Chris**: lo que cambia su diseño va como propuesta
OPCIONAL (atributo apagado por defecto) en la rama de sugerencias, nunca como corrección.

- **Reporte para Chris:** `docs/HALLAZGOS-CAJA-V3.md` en la rama de sugerencias (11 hallazgos,
  con causa, archivo y corrección). Todavía **no se ha hablado con Chris** ni abierto PR.
- **Errores corregidos (rama fix):** gota de NexSelect que no se animaba al reabrir; clic arriba
  del texto de NexInput dejaba el cursor al principio (WebKit ignora `line-height` en `<input>`:
  se resolvió con un clic en la membrana que enfoca al final); lista de NexSelect estirada en
  WebKit (`display: grid` en la capa superior → ahora flex); hendidura de la gota en listas
  anchas (cuello sin tramo recto, `liquidCapsule`); brillo de NexSurface que no seguía a la
  membrana (clipPath); NexButton con distinta redondez que los campos (`capsule` con
  `smoothing: 1` → 0; los campos leen `--nx-control-radius`); NexCheckbox rápido al marcar y
  lento al desmarcar (`9999px` → `20px 0 20px 0`, ¡no `10px 7px`, que pierde la hoja!).
- **Propuestas (rama sugerencias):** `NexCombobox` (texto libre con sugerencias; NexSelect no
  sirve porque mueve el foco); `NexProvider liquid="symmetric"` (gota simétrica; completa en
  fluid, a 1/3 en subtle, elastic sin cambio) con `--nx-liquid-thin` y `--nx-liquid-stretch`;
  `hitArea="membrane"` (el abombamiento responde al puntero); `radius` (none·sm·md·lg·pill) y
  `corner` (round·squircle). `squircle` en CSS solo lo pinta Chromium.
- **Para hablar con Chris (no tocado):** la discrepancia entre `cornerShape` y `smoothing` en las
  demás familias (membrane, fluid); el efecto *attract* se lee como error; NexDocs usa `<select>`
  nativos; NexSegmented y las pestañas no leen el token de radio (llevan la gota dentro).

### Llevar un cambio de NexFluid a la caja (paquetes `.tgz`)

No se instala desde GitHub (es un monorepo que hay que compilar). Pasos:

```bash
cd ~/nexfluid && git switch jesjack/feat/caja-v3 && npm ci && npm run build:lib
S=$(mktemp -d); V=~/sistema_ventas_v3/v_3/app/vendor; N=0.9.0-caja.12   # siguiente número
for p in foundation core components react; do
  mkdir -p $S/$p && cp -r packages/$p/{package.json,dist,README.md,LICENSE} $S/$p/
  (cd $S/$p && node -e "const p=require('./package.json');p.version='$N';require('fs').writeFileSync('package.json',JSON.stringify(p,null,2)+'\n')" && npm pack --pack-destination $V)
done
rm $V/*-0.9.0-caja.11.tgz          # el anterior
cd ~/sistema_ventas_v3/v_3/app && sed -i "s/0.9.0-caja.11.tgz/$N.tgz/g" package.json && npm install && rm -rf node_modules/.vite
```

- **Empaquetar SIEMPRE desde una copia temporal.** `npm version` dentro del repo de NexFluid
  (que usa *npm workspaces*) rompió su instalación local una vez; se arregló con `npm ci`.
- Los paquetes se piden entre sí con versión exacta: por eso `package.json` de la caja tiene
  `overrides` (`"$@nexfluid/..."`) para foundation, core y components. Cada paquete parcheado
  va en `dependencies` como `file:vendor/...tgz` y en `overrides`.
- `@nexfluid/sheets` viene de npm (0.9.0); no se ha modificado.
- Pendiente: convertir esto en un script `empaquetar.sh`.

## 6. Cosas aprendidas (para no repetirlas)

- WebKitGTK ≠ Chromium: probar en los dos. Para medir en WebKit sin ventana:
  `WEBKIT_DISABLE_COMPOSITING_MODE=1` + `Gtk.OffscreenWindow` + `WebKit2.WebView` desde Python
  (`gi`, WebKit2 4.1); `get_snapshot` permite sacar una captura PNG.
- La sesión es Wayland: `xdotool` no sirve para simular clics.
- `border-radius: 9999px` en una transición da animaciones asimétricas; usar el valor efectivo.
- En el prototipo, `hitArea`, `liquid`, `radius`, `corner` y los deslizadores de la gota se
  controlan desde el panel derecho para comparar en vivo.

## 7. Pendientes (en orden sugerido)

1. ~~Cerrar la fase 0~~ **Hecho (2026-11-24):** release medido (§3).
2. ~~Repasar D1–D23~~ **Hecho (2026-11-24):** `docs/repaso_decisiones_sin_calc.md`. Dejó cinco
   preguntas nuevas (P1–P5: botones configurables, NexSheets, canal con `camera_viewer`, Python
   para las cámaras, impresoras desde Rust) y recuerda que el código de caja de la V2 (`7410`)
   sigue público en GitHub.
3. Hablar con Chris: PR de la rama `jesjack/fix/nexinput-nexselect-webkit`; platicar las
   propuestas y los puntos de diseño del reporte.
4. Valores de la gota simétrica (`--nx-liquid-thin`, `--nx-liquid-stretch`): el usuario los iba
   a elegir con el depurador; anotarlos en el reporte.
5. Script `empaquetar.sh` (§5).
6. ~~Probar NexSheets~~ **Hecho y decidido (2026-11-24): NexSheets** para el carrito (detalle en
   `repaso_decisiones_sin_calc.md`, P2). En el prototipo: selector "Tabla propia | NexSheets" sobre
   el carrito y VENTAS REALIZADAS debajo (`src/hojas.ts`; Rust: `fechas_con_ventas`,
   `ventas_del_dia`). Errores de NexFluid encontrados, **por corregir en la rama de errores**:
   barras de scroll nativas visibles en WebKit pese a los carriles de NexScroll; el arrastre de su
   barra avanza una casilla y se traba; el borde de foco de la hoja va dentro de la zona con
   scroll (lo tapan los encabezados y lo recortan las esquinas); el borde de foco de la barra de
   fórmulas (1.5 px) sale desigual arriba y abajo. Propuestas: paleta de gráficas de solo 3
   colores (en editorial-light dos son naranjas casi iguales) y opción para que el encabezado de
   columna muestre solo el nombre, sin la letra. Trampas de la caja: medir la hoja POR FUERA de la
   zona con scroll (si no, las barras se retroalimentan) y resolver la fuente a px antes de medir
   con `<canvas>` (los tokens vienen en `rem`).
7. Fase 1 (núcleo en Rust con el esquema de la v2).
8. Más adelante (fase 2): corrector ortográfico del catálogo (ver `CLAUDE.md` de la raíz).
9. **DVR:** ninguna prueba contra el DVR fuera del embudo; leer `camaras_v3.md` §1 antes de tocarlo.
   La contraseña del DVR quedó visible en una sesión de trabajo (2026-11-24); el usuario no puede
   cambiarla fácil (hay que conectarle monitor y ratón al DVR).

## 8. Fase 1: el núcleo en Rust (`v_3/nucleo/`), estado al 2026-11-24

Crate sin interfaz (D18), probado con `cargo test` (16 pruebas; 2 de ellas solo a petición, ver
abajo). La app de Tauri (`v_3/app/src-tauri/src/lib.rs`) ya solo tiene comandos sobre el núcleo.

| Módulo | Qué hace | Equivale en la v2 |
|---|---|---|
| `base` | Abre la base (espera 15 s si está bloqueada, claves foráneas); `verificar_esquema` sin migrar; `abrir_solo_lectura` | `base_datos.py` |
| `carrito` | Agregar (suma si producto y precio coinciden), quitar, total | `table_modules/carrito.py` |
| `cobro` | `leer_monto` ("1,234.50", "1.234,50"…) y `Cobro` (alcanza / faltan $X, textos de la v2). Vacío = pago exacto (la v2 no lo permitía) | `dialogs/parseo.py`, `cobro_uno.py` |
| `ventas` | Registrar venta, evento y corte; `ventas_del_dia` (hoy desde el último corte, con el cambio dejado en caja) | `services/ventas_service.py` |
| `corte` | Denominaciones, `resumen_del_cambio` ("Sin cambio ($0.00)"…) | `services/corte_caja.py` |
| `catalogo` | Productos en minúsculas y únicos; `formatear_nombre`; búsqueda "contiene o iniciales" sin acentos ("bb" → blusa básica; las iniciales saltan "de", "y"…); códigos de barras | `catalogo_service.py`, `codigos_barras_service.py`, `filtrar_productos` |
| `sesiones` | Identidad del usuario y equipo IGUAL que la v2 (la versión del kernel termina en espacio: no recortar); `asegurar_usuario`, sesión, latido, cierre | `usuarios_service.py`, `identidad.py`, `seguimiento_sesion.py` |

**Pruebas contra la v2:** `nucleo/pruebas_v2/generar_casos.py` ejecuta el código REAL de la v2 (con
`~/sistema_ventas/v_2/.venv/bin/python3 -I`) sobre bases temporales y guarda `casos_v2.json` y
`esquema_v2.sql` (el esquema como lo crea la v2, con el usuario semilla `__default__` = id 1). Las
pruebas de `src/contra_v2.rs` repiten todo y comparan resultados y el contenido de las tablas.
Volver a correr el generador si cambia la v2. `serde_json` necesita `float_roundtrip` (si no, falla
por el último decimal al leer el JSON). Pruebas a petición:
`CAJA_DB=../app/datos/ventas_copia.db IDENTIDAD_V2="$(python3 … obtener_datos_usuario_sistema)" cargo test -- --include-ignored`.

**La app:** busca con el núcleo (iniciales), cobra con el comando `cobrar` (registra la venta
firmada con la sesión), VENTAS REALIZADAS en NexSheets de solo lectura (`useMarcoHoja` en
`src/marcoHoja.ts`), abre sesión al iniciar, latido cada 60 s, la cierra como normal al cerrar la
ventana (comprobado: sesión 200). Ruta de la base (D9): `CAJA_DB`, si no la carpeta de datos de la
app; en desarrollo, `datos/ventas_copia.db`. **Se niega a abrir `v_2/share/ventas.db`** (prueba).
Escribe SOLO en la copia; `copiar_base_real.py` la reemplaza (borra lo de prueba).

**DECIDIDO (2026-11-24, propuesta del usuario): la v3 tiene su PROPIA base.** `nucleo/src/esquema.rs`
con migraciones versionadas en `PRAGMA user_version` (`esquema/v1.sql`: la estructura de producción
de la v2 sin `autorizaciones_codigos`, más el usuario plantilla; `esquema/v2.sql`: `turno_caja`,
`permisos_usuario`, `codigo_caja`, `aperturas_caja`). Una migración publicada no se edita: los
cambios van en una nueva. `Base::abrir_v3` se NIEGA a migrar una base con tablas y versión 0 (la de
la v2): esa se importa. `nucleo/src/importar.rs` + `cargo run --bin importar_v2 -- <v2> <v3 nueva>`
copia todas las tablas conservando los ids, con la v2 en solo lectura; probado fila por fila (y que
el archivo de la v2 no cambia ni un byte) y con la copia real (236 ventas, 200 sesiones… idénticas).
La app abre `datos/ventas_v3.db` en desarrollo (ver `app/README.md`).

**Turno y permisos (`nucleo/src/caja.rs`):** `tomar_turno` / `turno_vigente` (D8); permisos por
usuario `desarrollador`, `abrir_caja_sin_limite`, `empleada` (D21); `como_abrir` → `Permiso`,
`VentanaDiaria` (empleada, una vez al día antes de la primera venta) o `Codigo` (también sin
permisos, D23); `registrar_apertura` deja el evento "APERTURA DE CAJA" y su fila en
`aperturas_caja` (llamarla SOLO cuando el cajón ya se abrió, como la v2); código de un solo uso
como SHA-256 con sal (`poner_codigo` solo con "sin límite"; `usar_codigo` lo bloquea).
28 pruebas en total.

**Turno y permisos en la app (hecho y probado con el usuario, 2026-11-24):** al abrir toma el turno
y lo comprueba cada 3 s; si otra caja lo toma, cierra la sesión como "desplazada", avisa
(evento `turno-perdido`) y sale (probado subiendo el número a mano). Cobrar y abrir caja exigen el
turno vigente. Botón "Abrir caja" e Intro con carrito vacío siguen `como_abrir`; si toca código y
no hay uno disponible, avisa sin pedirlo; si lo hay, lo pide (uno incorrecto no lo gasta). Cada
cobro registra su apertura ("venta"). Con "sin límite" y sin código (o usado), la caja pide uno
nuevo. El cajón es SIMULADO hasta la fase 3. Comandos: `estado_caja`, `abrir_caja`, `poner_codigo`.

**Permisos:** herramienta `cargo run --bin permisos -- <base v3> [<usuario> <permiso> [quitar]]`
(sin nombres en el código, D21; registra de antemano a un usuario de este equipo). Asignados en
`datos/ventas_v3.db`: nancy y miriamyaelicastanedaaparicio (id 194, registrada de antemano)
"sin límite"; emilymaya "empleada"; jesjack "desarrollador" + "sin límite" (**provisional**: el
usuario aún no decide; quiere poder hacer lo que hace hoy). **Al volver a importar desde la v2 se
pierden: asignarlos otra vez.** Pendiente: pantalla de administración (D21).

**Siguiente: fase 2** (pantalla de venta definitiva): afinar textos e interfaz (el usuario lo dejó
para aquí), botones configurables (P1, modelo de la v2), corte de caja desde la pantalla, prueba
en paralelo con la v2 sobre una importación reciente.
