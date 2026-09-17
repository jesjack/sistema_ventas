# Investigación: congelamiento total del sistema en camera_viewer (2026-09)

Resume la investigación que llevó a los commits `038dcf5` (fuga de memoria)
y `997acc1` (freeze de la GUI bajo zoom). Se documenta con detalle porque
costó varias rondas de instrumentación en vivo aislar las dos causas reales
-- vale la pena no tener que rehacer este trabajo si algo similar vuelve a
aparecer.

## Síntoma reportado

La aplicación de cámaras dejó de responder, y segundos después **todo el
sistema** se congeló, la pantalla se puso negra y cerró la sesión gráfica
completa -- dos veces. La segunda vez fue peor: ni siquiera se reinició el
entorno gráfico solo. El usuario notó que ambas veces coincidió con hacer
zoom in/out rápido y repetido sobre un panel de cámara en modo grabaciones,
aunque no estaba seguro de que fuera la única causa.

## Principio metodológico seguido

Explícito desde el inicio: **aislar la causa exacta mediante reproducción
antes de aplicar cualquier fix**, en vez de adivinar y probar mitigaciones
a ciegas. Esto incluyó dejar que el sistema se congelara una vez más de
forma controlada, con un monitor de emergencia corriendo de antemano, para
poder leer datos reales hasta el último instante.

### Monitor de emergencia (`crash_monitor.sh`)

Script que escribe a disco con `sync` después de cada línea (para que los
datos sobrevivan aunque el proceso completo, incluida la sesión que lo
lanzó, muera de golpe sin aviso):

```bash
while true; do
    ts=$(date '+%H:%M:%S.%N' | cut -c1-15)
    load=$(cat /proc/loadavg)
    mem=$(free -m | awk '/^Mem:/{print "mem_used="$3"MB mem_free="$4"MB mem_avail="$7"MB"}')
    top_procs=$(ps -eo pid,pcpu,pmem,rss,comm --sort=-pcpu --no-headers | head -6 | tr '\n' '|')
    echo "$ts load=$load $mem procs=[$top_procs]" >> "$LOG"
    sync
    sleep 0.5
done
```

Este patrón (poll corto + flush explícito) se reutilizó varias veces
durante la investigación y es la técnica de referencia para cualquier
futuro "necesito ver qué pasó justo antes de que todo muriera".

## Causa raíz #1: fuga de memoria sin límite en reproducción de grabaciones

### Evidencia del crash real

El log del monitor mostró la RSS del proceso de `camera_viewer` creciendo
de una base estable (~160MB) con un patrón de **duplicación repetida**
hasta superar 6.9GB, seguido de un salto de **2 minutos 8 segundos** entre
líneas del log -- el sistema entero quedó paralizado (sin memoria
disponible, probablemente en swap-thrashing) el tiempo suficiente para que
ni `ps`/`free` pudieran ejecutarse a tiempo.

### Mecanismo

`DVRClient._play_chunk()` (reproducción de grabaciones) leía un frame del
archivo descargado y lo emitía a la GUI (`recording_frame_ready.emit(...)`,
señal Qt entre hilos) **sin ningún freno**, pasando de inmediato al
siguiente frame. La vista en vivo (`_live_channel_worker`) sí tenía un
freno (`ready_event`/`notify_frame_consumed()`), pero grabaciones no.

Si el hilo de la GUI se atrasaba un poco (el disparador identificado:
ráfagas de eventos de zoom), los frames pendientes (cada uno un arreglo de
varios MB) se acumulaban sin límite en la cola interna de Qt entre hilos.
Entre más se atrasaba la GUI, más rápido crecía la cola, y entre más
grande la cola, más lenta se ponía la GUI para procesarla -- de ahí el
patrón de duplicación.

### Reproducción aislada (antes de tocar código)

Un script standalone con un hilo de fondo emitiendo frames sintéticos a
25fps por una señal Qt real `Signal(int, object)` cruzando hilos, sin
ningún freno, hizo que la RSS saltara a **655MB en el primer segundo** --
ni siquiera hizo falta simular que la GUI estuviera ocupada. Confirmó el
mecanismo de forma directa.

### Fix

Un semáforo por canal (`RECORDING_MAX_INFLIGHT_FRAMES = 2`) en
`_play_chunk`: antes de emitir un frame, el hilo espera un permiso libre
(nunca descarta -- a diferencia de vivo, aquí perder un frame se notaría
como un hueco/tirón en el video del usuario). La GUI libera un permiso
justo después de pintar cada frame
(`DVRClient.notify_recording_frame_consumed`).

Se discutió explícitamente la capacidad del semáforo: 1 permiso (como
vivo, pero bloqueando en vez de descartar) ya elimina el riesgo de
crecimiento sin límite; se optó por **2 permisos** (propuesta del usuario)
-- da un pequeño colchón de suavidad (hasta 3 frames en memoria por canal:
1 esperando turno en el hilo + 2 en vuelo) a cambio de una diferencia de
memoria trivial.

### Verificación

226 segundos... [ver verificación de la causa #2 más abajo, la prueba
final cubre ambas]. Antes de eso, una prueba de 110s contra el DVR real
con ráfagas de zoom cada 4s mostró la memoria subir de ~135MB a un techo
de ~300MB y quedarse ahí fluctuando, sin tendencia de crecimiento --
contraste directo con los 655MB en el primer segundo de la reproducción
sin freno.

**Commit:** `038dcf5`

## Causa raíz #2: freeze de la GUI por un ciclo scrollbar↔resize

### El fix de memoria no fue suficiente

Con la memoria acotada, el sistema **ya no se congelaba entero** -- pero
la app en sí seguía poniéndose "no responde" bajo zoom agresivo, hasta
requerir forzar la salida.

### Los intentos sintéticos fallaron (y eso también fue información)

Se intentó reproducir el freeze de forma aislada, sin éxito, en varias
formas:

- Medir el costo de repintado puro de un panel con un frame real
  (960x1080, confirmado vía `ffprobe`) bajo una ráfaga de 300 eventos de
  zoom: se resolvía en <100ms.
- Simular los 4 canales con hilos de decodificación **reales** contra el
  DVR real, más una ráfaga de 1500 eventos de zoom: recuperación en
  ~89ms.
- Rampa de zoom sostenido hasta el tope (`MAX_ZOOM=40`): sin ningún
  "acantilado" de rendimiento.

Cruzando con el log del sistema durante el freeze real, tampoco había
saturación total de CPU (load promedio ~3.0-3.7 de 4 núcleos posibles,
`gnome-shell` casi inactivo) -- descartando tanto "mi código de zoom es
caro" como "los 4 núcleos están saturados por la decodificación" como
explicación completa.

### Instrumentación en vivo (la clave para encontrarlo)

Ante la imposibilidad de reproducirlo sintéticamente, se instrumentó la
app real para capturar datos exactamente cuando el usuario reprodujera el
freeze con su propio scroll físico:

1. **Latido de la GUI**: un `QTimer` de 100ms en `MainWindow` que
   registraba el intervalo real entre disparos, más contadores de eventos
   de zoom y de `set_frame()` por canal. Un salto grande entre líneas
   prueba (y cuantifica) un bloqueo real del hilo principal sin necesidad
   de adivinar la causa de antemano.
2. **Watchdog de pila Python** (`faulthandler.dump_traceback_later`):
   rearmado en cada latido sano; si el hilo de la GUI no vuelve a
   rearmarlo en 1.5s, un mecanismo interno en C (independiente del GIL)
   vuelca la pila de todos los hilos a un archivo -- funciona incluso si
   el hilo principal está genuinamente atorado, no solo lento.
3. **Watcher con `py-spy`** corriendo como root (necesario:
   `ptrace_scope=1` exige privilegios para adjuntarse a un proceso ajeno):
   vigilaba el log del latido y, ante una pausa sostenida, capturaba la
   pila **nativa** (C/C++, no solo Python) -- para ver más profundo que
   `faulthandler` si hiciera falta.

### Ronda 1: confirma bloqueo real, no solo lentitud

El latido (estable en ~100ms) **se detuvo por completo** durante el
freeze -- no se puso lento, dejó de aparecer del todo por más de 3
segundos, mientras los 4 hilos de descarga seguían vivos, reportando
esperas de 1 a 20+ segundos por un permiso del semáforo que la GUI nunca
liberaba. Sin excepción de Python (`Terminado (killed)`, no un traceback)
-- descartaba un bug propio con una excepción de por medio.

### Ronda 2: el stack trace exacto

(Se corrigió antes un defecto del watcher: nunca disparaba porque los
hilos de descarga seguían escribiendo líneas "espero..." al mismo log,
enmascarando la inactividad real del latido -- había que contar
específicamente líneas de "latido", no cualquier escritura al archivo.)

El volcado de `faulthandler` esta vez atrapó al hilo principal **no**
parqueado en `app.exec()` (que es donde está siempre, sano o no, y por
tanto no distingue nada) sino dentro de:

```
File "camera_panel.py", line 80 in _update_transform
File "camera_panel.py", line 95 in resizeEvent
```

Dato clave: el usuario no estaba redimensionando la ventana. Si
`resizeEvent` se disparaba de todos modos, algo se estaba redimensionando
solo.

### El mecanismo

`CameraPanel` heredaba `ScrollBarAsNeeded` de `ZoomPanGraphicsView` (nunca
lo sobreescribía, a diferencia del timeline, que sí lo hace con su propio
scrollbar flotante). Y `_update_transform()` calcula la escala del frame a
partir del tamaño **actual** del viewport (`_fit_scale()`). Esto acopla
dos cosas que se retroalimentan:

1. Al hacer zoom, el contenido puede llegar a exceder el viewport →
   aparece una scrollbar.
2. La scrollbar le quita espacio al viewport → dispara `resizeEvent`.
3. `_update_transform()` recalcula la escala contra el viewport (ahora
   más chico) → el contenido puede volver a caber → la scrollbar
   desaparece → el viewport vuelve a crecer → dispara `resizeEvent` de
   nuevo.

Bajo un gesto de zoom rápido y sostenido esto puede ciclar
continuamente. No se pudo determinar con certeza absoluta cuál paso
exacto del ciclo era el lento (no hubo excepción de Python, ni error de
GPU/kernel en `dmesg`/`journalctl`, ni saturación de CPU a nivel sistema
que lo explicara por sí sola) -- la hipótesis más consistente con toda la
evidencia es un costo síncrono dentro de Qt/el compositor de Wayland al
reconfirmar el tamaño del widget, que se vuelve significativo solo cuando
se repite cientos de veces por segundo.

### Fix

- `CameraPanel`: ambas políticas de scrollbar a `ScrollBarAlwaysOff` --
  el paneo ya funciona por arrastre (`ScrollHandDrag`), así que no se
  pierde nada, y esto hace el ciclo **estructuralmente imposible** en vez
  de solo menos probable.

Junto con esto se aplicaron dos optimizaciones complementarias
(reducen el costo del zoom en sí, independientemente del ciclo):

- `CameraPanel`: antialiasing desactivado de forma permanente -- la
  escena de un panel de cámara nunca dibuja nada vectorial (solo un
  único `QGraphicsPixmapItem`), a diferencia del timeline (que sí
  comparte la misma clase base y sí dibuja formas). Sin beneficio visual
  ahí, solo costo.
- `ZoomPanGraphicsView`: throttle de ~60Hz que agrupa una ráfaga de
  eventos de rueda en una sola actualización de transformación en vez de
  una por cada tick; `CameraPanel` además apaga `SmoothPixmapTransform`
  mientras el usuario mueve la rueda activamente y lo reactiva ~150ms
  después de que se detiene.

  Medido con metodología corregida (CPU real consumida vía
  `time.process_time()`, esperando con un `QEventLoop` real en vez de un
  `while` con busy-spin, que infla artificialmente el número): ~35% menos
  CPU en una ráfaga sostenida de 300 eventos de zoom (172.8ms → 111.8ms).
  Una medición anterior, con una metodología distinta y no comparable
  (dispatch vs. drenado sin espera real), había arrojado un "8x" que
  resultó ser incorrecto -- queda anotado aquí para no repetir el error.

**Commit:** `997acc1`

### Verificación final

226 segundos de reproducción real contra el DVR (4 canales) con zoom
agresivo sostenido hecho directamente por el usuario:

- **0** gaps de latido por encima de 150ms (de 2262 líneas totales).
- **0** líneas de espera de semáforo (la GUI nunca se atrasó ni una vez).
- **0** disparos del watchdog de `faulthandler`.
- Cierre voluntario y limpio del proceso (no "killed").

## Herramientas y técnicas (para referencia futura)

- **`crash_monitor.sh`** (poll corto + `sync` por línea): sobrevive a que
  el proceso que lo generó, o el sistema entero, mueran de golpe.
- **Reproducción aislada antes de tocar código**: scripts standalone que
  imitan el patrón exacto sospechoso (p. ej. un hilo de fondo emitiendo
  por una señal Qt real) para confirmar o descartar una hipótesis sin
  arriesgar el sistema real.
- **`time.process_time()` vs. `time.perf_counter()`**: para medir costo
  de CPU real hay que restar las esperas intencionales (timers de
  debounce, etc.) -- de lo contrario se mide tiempo de reloj, no trabajo.
- **`QEventLoop` + `QTimer.singleShot` para esperar sin busy-spin**: un
  `while time.perf_counter() < deadline: app.processEvents()` infla el
  CPU medido con el costo del propio spin, no del trabajo real.
- **`faulthandler.dump_traceback_later()` como watchdog**: rearmado desde
  un latido sano (patrón "pet the watchdog"), dispara solo si el hilo
  principal deja de ejecutar Python por más de N segundos -- funciona
  incluso si el hilo está genuinamente atorado (usa un mecanismo de C
  independiente del intérprete).
- **`py-spy`** para pila nativa (C/C++), útil cuando `faulthandler` no
  alcanza a ver más allá de una llamada C++ bloqueante (p. ej.
  `app.exec()`). Requiere privilegios (`ptrace_scope=1` en este sistema)
  para adjuntarse a un proceso que no es hijo directo.
- **`zenity --password` como `SUDO_ASKPASS`**: cuando no hay una TTY
  interactiva disponible para que `sudo` pida la contraseña (como en esta
  interfaz), un helper gráfico (`SUDO_ASKPASS=... sudo -A ...`) permite
  pedirla por un cuadro de diálogo en la pantalla real en vez de fallar.

## Pendiente (no bloqueante, anotado para el futuro)

- Los 4 canales siguen decodificando H.264 960x1080@30fps **por
  software** (el build de OpenCV/FFmpeg de este entorno no tiene
  aceleración VAAPI/QSV) -- no causó este freeze en particular, pero
  sigue siendo el mayor costo de CPU de la app. Ideas ya discutidas y
  descartadas por ahora (no había evidencia de que hicieran falta):
  frame-skipping, decodificación con aceleración de hardware, downloads
  en `/dev/shm` en vez de disco, un "circuit breaker" basado en carga de
  CPU.
