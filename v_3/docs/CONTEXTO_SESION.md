# Contexto para continuar la V3 (Rust + Tauri + NexFluid)

Documento de traspaso entre sesiones de trabajo (con o sin Claude). **Léelo antes de seguir.**
Última actualización: 2026-11-23, al cerrar la fase 0.

## 1. La decisión de fondo

El diseño V3 original (`docs/mapa_v2.md`, `docs/diagrama_*`, decisiones D1–D23) seguía usando
LibreOffice Calc como interfaz, con dos intérpretes (UNO y venv) y un socket. **El 2026-11-23 se
decidió dejar Calc** y rehacer la caja con:

- **Rust + Tauri 2**: la lógica (SQLite, impresoras, cajón, permisos) en Rust; la interfaz en un
  webview (WebKitGTK en Linux, WebView2 en Windows).
- **React 19 + NexFluid** (la librería de interfaz de Chris, `gibran564/nexfluid`, MIT) para la
  interfaz.
- **`camera_viewer` se queda en Python** como proceso hijo (como ya decía D22): son ~22 mil líneas
  que funcionan. YOLO no se usa (solo `cameras/test_ia.py`, un experimento).

Consecuencia: muchas decisiones D1–D23 eran sobre Calc/UNO/Basic y **ya no aplican** (dos
intérpretes, socket, botones en Basic, `consumir_tab`, foco de Calc, hook global de teclado con
root, prehorneado). Las reglas de negocio **sí siguen**: roles y permisos (D21), reglas del cajón
y del código de un solo uso (D21/D23), App de larga vida con camera_viewer como hijo (D22), log
único por día. Falta repasar D1–D23 y marcar cuáles siguen (tarea pendiente, ver §7).

La v2 (`~/sistema_ventas`, rama `v2`) **sigue en producción** en la PC de la caja hasta que la v3
haga todo lo que hace la v2.

## 2. Plan por fases

| Fase | Qué | Estado |
|---|---|---|
| 0 | Prototipo: Tauri + NexFluid en la PC de la caja, medir | **Hecha** (falta medir en release, §7) |
| 1 | Núcleo: Rust lee/escribe `ventas.db` con el MISMO esquema; reglas del carrito y cobro con pruebas contra la v2 | Siguiente |
| 2 | Pantalla de venta completa (captura, carrito, cobro, VENTAS REALIZADAS), en paralelo con la v2 sobre una copia | |
| 3 | Hardware: ticket, cajón (reglas D21/D23), etiquetas | |
| 4 | Administración: usuarios, roles, turnos, botones | |
| 5 | Cámaras: lanzar `camera_viewer` (Python) como hijo, "VER EN CÁMARAS" | |
| 6 | Instaladores de Tauri (.deb/AppImage, .msi) | |
| 7 (opcional) | Pasar las cámaras a Rust | |

## 3. Resultados de la fase 0 (PC de la caja: 4 núcleos, 7.6 GB, Intel HD 630, Zorin OS 17, Wayland)

- Tecla → pantalla: mediana **19 ms**, p95 27 ms (modo desarrollo, sin optimizar).
- Consulta a Rust (autocompletado): mediana **2 ms**.
- Escáner: **16 ms/tecla** contra 80–150 ms de una persona: se distingue sin hook global.
- WebKitGTK 2.50.4 funciona; tuvo varias diferencias con Chromium que se corrigieron en NexFluid.

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

1. Cerrar la fase 0: compilar en **release** (`npm run tauri build`, fuera de horario) y medir;
   escribir la conclusión en `v_3/docs/`.
2. Repasar D1–D23 de `docs/mapa_v2.md`: marcar cuáles siguen sin Calc.
3. Hablar con Chris: PR de la rama `jesjack/fix/nexinput-nexselect-webkit`; platicar las
   propuestas y los puntos de diseño del reporte.
4. Valores de la gota simétrica (`--nx-liquid-thin`, `--nx-liquid-stretch`): el usuario los iba
   a elegir con el depurador; anotarlos en el reporte.
5. Script `empaquetar.sh` (§5).
6. Decidir NexSheets contra tabla propia para el carrito (se usó tabla propia, no se evaluó NexSheets).
7. Fase 1 (núcleo en Rust con el esquema de la v2).
8. Más adelante (fase 2): corrector ortográfico del catálogo (ver `CLAUDE.md` de la raíz).
