# Resultados de las pruebas de estrés del DVR (Dahua XVR51xxHS-S2)

Este documento resume la investigación que llevó al diseño actual de
`DVRClient` en `dvr_client.py` (descarga por bloques + reproducción local
para grabaciones, límite de concurrencia en vivo). Ver
`camera_viewer/DVR_HARDWARE.md` para las especificaciones del equipo.
Herramienta usada: `cameras/dvr_stress_test.py` (standalone, no depende de
`camera_viewer`).

## Contexto

En producción, `camera_viewer` dejaba de reproducir tanto en vivo como en
grabaciones tras unos segundos/minutos de uso, y el DVR quedaba sin
responder a **cualquier** cliente (confirmado con `curl`/`nc` puros, sin
relación alguna con la app). Esto se investigó de forma metódica,
escalando la carga contra el DVR real un escalón a la vez, deteniéndose de
inmediato ante el primer signo de fallo.

## Metodología

- Chequeo de salud liviano (una sola petición HTTP CGI, sin reintentos)
  antes y después de cada prueba.
- Escalar de a un canal a la vez (1, 2, 3, 4 conexiones simultáneas).
- Medir: latencia de apertura, tiempo al primer frame, fps sostenidos, y
  **Mbps reales** (leyendo los contadores de bytes de la interfaz de red,
  no estimados por tamaño de frame decodificado).
- Ante cualquier fallo de salud, detenerse de inmediato y esperar a que un
  humano reinicie el DVR antes de continuar.

## Resultados

### Vista en vivo (RTSP, substream)

| Prueba | Resultado |
|---|---|
| 1, 2, 3, 4 conexiones simultáneas (8s c/u) | **Todas pasaron limpio.** ~18 fps por canal, 352×240, ~0.36-0.88 Mbps agregados |
| Persistencia: 1 canal sostenido 5 minutos | **Sin degradación.** ~15 fps constantes, salud OK en los 9 muestreos (cada 30s) |

**Conclusión: la vista en vivo (hasta 4 canales a la vez) es segura tal
como estaba diseñada.** No se encontró ningún límite ahí -- no se cambió
nada de esa ruta de código más allá de la reconexión con backoff que ya
existía.

### Grabaciones (HTTP `loadfile.cgi`)

| Prueba | Resultado |
|---|---|
| 1, 2, 3 conexiones simultáneas, sin freno (máxima velocidad) | OK -- 30-38 Mbps agregados |
| **4 conexiones**, sin freno, tras haber corrido 1→2→3 antes | **FALLÓ, reproducido 2/2 veces.** Un canal se atasca ~31s al abrir, los demás caen de 200-400 fps a 8-17 fps, el throughput colapsa a ~1.3-1.4 Mbps, y el DVR queda sin responder después |
| 4 conexiones, sin freno, **en frío** (sin niveles previos) | Pasó una vez -- no es un límite de "4 sesiones totales desde el arranque", sino de **pico de concurrencia acumulado en la sesión de prueba** |
| 1, 2, 3 conexiones, **a ritmo real** (pausando cada frame como hace la app) | OK -- pero con **10 veces menos ancho de banda** (~3-5.7 Mbps agregados) |
| **4 conexiones, a ritmo real**, tras 1→2→3 | **FALLÓ igual, síntoma idéntico** (mismo canal atascado ~31.25s) pese al ancho de banda mucho menor |
| Persistencia: 1 canal, un solo clip | OK -- el clip se acabó solo (24s a máxima velocidad), sin degradación |
| **Ciclos repetidos: 2 conexiones a la vez, alternando pares (1,2)/(3,4), 52 ciclos en 5 minutos (104 sesiones nuevas totales, cooldown de 1s)** | **Todas OK. Cero fallos de salud.** |

**Conclusiones clave:**

1. **El ancho de banda NO es la causa.** Bajar el Mbps 10x (ritmo real vs.
   sin freno) no evitó el fallo en el nivel 4 -- mismo síntoma, mismo
   punto exacto de atasco.
2. **No es un límite acumulado en el tiempo.** 104 sesiones repartidas en
   ciclos de a 2, durante 5 minutos, no rompieron nada -- muchas más
   sesiones totales que las 4 que bastan para romperlo cuando están en el
   pico de concurrencia.
3. **Es un límite de PICO de concurrencia de sesiones `loadfile.cgi`**,
   entre 3 (confirmado seguro, repetidamente) y 4 (falla reproducible).

## Decisión de diseño

Ya que el ancho de banda no es el problema, y que las grabaciones se
descargan mucho más rápido que tiempo real (8-15x medido), `DVRClient`
(commit que introduce este archivo) reemplazó la lectura directa del DVR
durante la reproducción de grabaciones por un esquema de **descarga por
bloques + reproducción local**:

- Cada canal descarga un bloque acotado de video (`DOWNLOAD_CHUNK_SECONDS`,
  45s) a un archivo temporal local -- solo copia bytes, sin decodificar.
- Nunca hay más de `MAX_CONCURRENT_RECORDING_DOWNLOADS` (2, con margen de
  sobra bajo el límite real de 3) descargas en curso a la vez entre los 4
  canales -- un semáforo compartido lo garantiza.
- La reproducción en sí lee del archivo local ya descargado, a ritmo real
  -- no toca la red para nada, así que **no cuenta contra el límite del
  DVR**. Los 4 canales pueden reproducirse a la vez sin importar cuántos
  estén "reproduciendo" en un momento dado, porque solo las *descargas*
  compiten por el cupo.
- Al pasar a vista en vivo, se espera (con margen amplio) a que todos los
  hilos de reproducción terminen y se drena el semáforo de descargas por
  completo antes de la primera conexión RTSP -- nunca debe haber una
  sesión de grabación abierta al mismo tiempo que una de vivo.

Validado con una prueba real contra el DVR de producción (búsqueda de
clips reales, reproducción por bloques con transición de canal y de clip,
cambio a vivo a mitad de sesión): cero errores, cero reintentos, DVR sano
antes y después, sin archivos temporales residuales.

## Adenda (2026-09-18): ¿es necesaria la pausa de cortesía entre descargas?

La pausa de 1 s entre sesiones (`POST_DOWNLOAD_GAP`) ya estaba puesta en todas
las pruebas de arriba, así que nunca se había medido si hace falta. Se probó
contra el DVR real, por fases, con una comprobación de salud cada segundo y
corte inmediato ante el primer fallo. Descargas de 15 s, canales rotando:

| Fase | Trabajos | Fallos | Primer byte (media / máx) |
|---|---|---|---|
| 1 hilo, pausa 1.0 s (control) | 10 | 0 | 0.16 s / 0.20 s |
| 1 hilo, pausa 0.25 s | 15 | 0 | 0.15 s / 0.25 s |
| 1 hilo, **pausa 0** (seguidas) | 30 | 0 | 0.16 s / 0.32 s |
| 1 hilo, cortando a los 0.3 s y **reabriendo al instante** | 20 | 0 | 0.17 s / 0.35 s |
| 2 hilos, pausa 0, con un candado que evita que ambos cierren/abran a la vez (pico contado ≤ 3) | 30 | 0 | 0.21 s / 0.52 s |

- Sin pausa, el DVR no tardó más en dar el primer byte ni falló: no hay señal de que
  necesite tiempo para liberar una sesión cerrada, ni de que un corte brusco deje
  sesiones "fantasma".
- **Sin probar** (a propósito): 2 hilos que cierran y abren exactamente al mismo
  tiempo con pausa 0, donde el pico contado podría llegar a 4 (la zona que
  reproduce el fallo) si existiera algún retardo de liberación.
- Anomalía sin explicar: una consulta de salud tardó 4.29 s durante la fase de
  control (pausa 1.0 s, o sea NO por quitar la pausa) y otra 1.92 s en la fase sin
  pausa; en total 1 de 108 comprobaciones pasó de 3 s. Posible relación con el
  arranque/lectura del disco del DVR al servir una descarga; no confirmado.

## Adenda 2 (2026-09-18): ¿cuántas sesiones de consultas ligeras aguanta el DVR?

Consultas `magicBox.cgi?action=getSystemInfo` (con autenticación nueva en cada
petición) y objetos de búsqueda `mediaFileFind` abiertos a la vez, en
escalera, con corte ante la primera anomalía. Cada nivel duró 8 s.

| Situación | Resultado |
|---|---|
| Solo consultas ligeras, 1 a **12** simultáneas | Sin fallos. El DVR atiende ~19-22 peticiones/s en total; más simultaneidad solo alarga la latencia (mediana 76 ms con 1, 456 ms con 12) |
| Hasta **6** objetos de búsqueda abiertos a la vez, sin descargas | Sin fallos |
| **2 descargas de clips corriendo** + 1 o 2 consultas ligeras | Sin fallos; las descargas no se afectan (37 trabajos, 0 fallos, primer byte 0.31 s). Las consultas van ~3-4 veces más lentas (11/s → 3/s con 1 hilo) |
| 2 descargas + **3** consultas ligeras a la vez | **ReadTimeout (6 s) en 3 de 44 peticiones** |
| 2 descargas + **3** objetos de búsqueda abiertos | **ReadTimeout** |

- El límite de 3 sesiones NO aplica a las consultas ligeras por sí solas
  (12 sin problema), pero **sí interactúan con las descargas**: con 2
  descargas activas caben 2 consultas ligeras más (4 en total) y con 3 (5 en
  total) aparecen tiempos de espera agotados, sin que el DVR se caiga (siguió
  respondiendo en 0.07 s al terminar).
- Cada nivel se corrió una sola vez; el hallazgo en 5 sesiones totales salió en
  dos pruebas distintas (consultas y objetos de búsqueda), pero conviene repetirlo
  antes de tomarlo como límite firme.

### Corrección a la Adenda 2 (misma fecha): los atascos parecen intermitentes, no un límite de sesiones

Se repitió la prueba con **una sola** descarga activa (dos corridas, la segunda con
20 s de calentamiento). Aun con **una sola consulta ligera a la vez** hubo
atascos: en la primera corrida la consulta casi no avanzó (1 petición en 8 s + un
`ReadTimeout`) y en la segunda, tras un calentamiento limpio (9.2 peticiones/s) y
una pasada perfecta (9.4/s), la siguiente pasada tuvo un `ConnectTimeout` de 6 s.
Los objetos de búsqueda abiertos (1 a 6) pasaron limpios en ambas corridas, y las
descargas nunca fallaron (35 y 16 trabajos, 0 fallos).

- Como el atasco también aparece con 1 consulta, el "con 2 descargas caben 2
  consultas y con 3 aparecen timeouts" de la Adenda 2 **no es fiable**: pudo ser el
  mismo atasco intermitente cayendo justo en esos niveles.
- Lo que sí se sostiene: sin descargas, 1-12 consultas simultáneas no fallaron; con
  descargas activas aparecen, cada cierto tiempo (se vieron 4 en unos 4 minutos de
  descarga, más los picos de 4.29 s y 1.92 s de la prueba de la pausa), atascos de
  varios segundos en las consultas ligeras, aun con una sola. Las descargas no se
  afectan y el DVR siempre se recuperó.
- Falta medir la frecuencia y la duración de esos atascos (sondeo continuo de una
  consulta con timeout largo, en reposo vs. con 1 descarga) y si coinciden con algo
  concreto (inicio de trabajos, cruce de archivos de grabación).

## Adenda 3 (2026-09-18): sondeo continuo de consultas ligeras con 0, 1 y 2 descargas

Una consulta `getSystemInfo` cada ~0.25 s (timeout 30 s) durante toda la prueba;
tres tramos de 4 minutos con 0, 1 y 2 descargas de clips de 45 s seguidas y sin
pausa (con un candado para que no cierren y abran a la vez). La prueba se cortó
sola a los 63 s del tramo de 2 descargas por una descarga fallida.

| Tramo | Consultas | Errores | Latencia p50 / máx | Atascos > 3 s |
|---|---|---|---|---|
| 0 descargas (240 s) | 959 (4.0/s) | 0 | 78 ms / 0.13 s | 0 |
| 1 descarga (240 s) | 813 (3.4/s) | 0 | 93 ms / 10.04 s | 5 (7-10 s cada uno; 38.7 s en total por encima de 1 s) |
| 2 descargas (63 s, cortado) | 92 (1.4/s) | 0 | 358 ms / 10.59 s | 1 |

- **En reposo el DVR es estable**: cero atascos en 4 minutos. Los atascos los provoca
  tener una descarga activa.
- **Con 1 descarga los atascos son periódicos**: a los 274, 341, 410 y 480 s (cada
  ~69 s) con duraciones crecientes (5.8, 7.4, 8.4 y 10.0 s). El siguiente, a los 550 s,
  cayó en el tramo de 2 descargas (10.6 s), aun con 20 s sin descargas antes; sin
  descargas (tramo 0) no hubo ninguno. Hipótesis sin comprobar: una tarea periódica
  interna del DVR que bloquea las consultas mientras se sirve una descarga.
- Las descargas en sí no se afectan con 1 (116 trabajos, 0 fallos, primer byte máx 0.39 s).
- **Primer fallo de descargas en todas las pruebas**: con 2 descargas sin pausa, 2
  fallaron con `ConnectionError` a los 63 s (el DVR siguió sano después). Esto
  **debilita** la conclusión de la Adenda 1 de que la pausa de cortesía no hace falta:
  vale para 1 hilo, no está demostrado para 2 hilos sostenidos. No quitar la pausa.
- Pendiente: 2 descargas CON la pausa de 1 s durante minutos (configuración real),
  descargas con velocidad limitada (por si el atasco es por saturar la CPU/red del
  DVR), y registrar el rango de video de cada descarga junto a cada atasco (por si
  coinciden con el cruce de archivos de grabación).

## Adenda 4 (2026-09-18): 2 descargas simultáneas con y sin pausa de cortesía de 1 s

Se usó el `RecordingDownloadManager` real (2 hilos) alternando `post_download_gap`
1 s / 0 s, con la app cerrada. Rangos de 45 s de las 12:00-12:50, canales rotando.

**Fase 0: primer cuadro de los 4 canales con 2 cupos** (6 repeticiones por configuración;
tiempo hasta que llegan los 4 clips; se excluyen las repeticiones con atasco):

| Pausa | Canales 1-2 | Canales 3-4 | Repeticiones con atasco |
|---|---|---|---|
| 1 s | 2.8 s | 6.4 s (5.95-6.74) | 2 de 6 (53.9 s y 42.2 s; la 2.ª con 2 descargas fallidas) |
| 0 s | 2.6 s | 5.3 s (5.20-5.51) | 2 de 6 (24.7 s y 15.8 s) |

La pausa cuesta ~1.1 s solo en el primer cuadro de los canales 3 y 4.

**Fases continuas** (4 min cada una, 2 descargas seguidas + `getSystemInfo` cada ~0.25 s):

| Fase | Consultas | Mediana | Máx | Atascos > 3 s | Tiempo > 1 s | Descargas |
|---|---|---|---|---|---|---|
| 1 s (P1) | 449 | 0.10 s | 25.0 s | 5 | 60.8 s | 122 ok, 0 fallos |
| 0 s (P2) | 183 | 0.38 s | 28.1 s | 10 | 126.4 s | 102 ok, 0 fallos |
| 1 s (P3) | 534 | 0.10 s | 9.7 s | 3 | 28.5 s | 144 ok, 0 fallos |
| 0 s (P4) | 24 (cortada a los 73 s) | 0.36 s | 30.1 s (timeout) | 3 | 58.7 s | 11 ok, 2 `ConnectionError` |

- Sin pausa las consultas ligeras van ~3.7 veces más lentas (mediana 0.36-0.38 s contra 0.10 s),
  con más atascos, y hay fallos de descarga: 2 de 3 corridas sin pausa (con la de la Adenda 3) contra
  0 de 2 con pausa. Las descargas con pausa no rinden menos (122 y 144 contra 102 trabajos).
- Los fallos coinciden con el final de un atasco de ~30 s del DVR.
- La pausa **no elimina** los atascos: aparecen con ella (hasta 25 s) y también hubo 2 descargas fallidas
  con pausa en la fase 0 (tras un atasco de 42 s). Solo reduce su frecuencia y su duración.
- Los atascos pueden ser de hasta 30 s (antes se veían 10 s), y las propias descargas se atascan en
  el primer byte (15-54 s en 4 de 12 repeticiones, con y sin pausa). Los timeouts de consultas ligeras
  deben ser mayores a 30 s o se convierten en fallos.
- DVR sano al final: 4 consultas de ~0.08 s, ping sin pérdidas.
- n pequeño (2-3 corridas por configuración): tendencia clara pero no concluyente.

## Adenda 5 (2026-09-19): prueba de aceptación del embudo con carril ligero (2 descargas + 1 o 2 hilos ligeros)

Configuración de producción (commit c9c9fa1): 2 descargas seguidas con pausa de 1 s por el
`RecordingDownloadManager` y consultas `getSystemInfo` por el `LightQueryManager` (timeouts 5/35 s,
3 intentos, 1 s entre ellos) con 2 solicitantes continuos y una espera de 0.25 s entre consultas. Cuatro
tramos de 5 min en orden A-B-B-A (A = 1 hilo ligero, B = 2 hilos), 30 s entre tramos, app cerrada.

| Tramo | Hilos ligeros | Consultas | Fallos | Reintentos | Mediana / p90 / p99 | Máx | Tiempo en espera > 1 s* | Descargas |
|---|---|---|---|---|---|---|---|---|
| A1 | 1 | 872 | 0 | 0 | 0.11 / 0.52 / 10.2 s | 30.2 s | 284 s | 131 ok, 0 fallos |
| B1 | 2 | 1159 | 0 | 0 | 0.12 / 0.35 / 1.7 s | 26.6 s | 146 s | 167 ok, 0 fallos |
| B2 | 2 | 995 | 0 | 2 | 0.12 / 0.40 / 7.5 s | 36.3 s | 193 s | 148 ok, 0 fallos |
| A2 | 1 | 1154 | 0 | 1 | 0.10 / 0.41 / 5.9 s | 24.2 s | 143 s | 170 ok, 0 fallos |

\* Suma de las esperas > 1 s de los 2 solicitantes (un mismo atasco cuenta dos veces).

- **Cero fallos en 4180 consultas y 616 descargas.** Antes, sin embudo y sin pausa, 2 de 3 corridas de
  2 descargas tuvieron descargas fallidas. Los 3 reintentos (el máximo de 36.3 s es un intento que
  agotó los 35 s de lectura y el reintento lo resolvió) evitaron 3 fallos que habrían llegado a la interfaz.
- **Los atascos siguen ahí**, de 6 a 36 s y cada ~69-70 s (410.7, 479.7, 550.4, 619.5 s en B1), y afectan
  a los dos solicitantes a la vez: parecen del DVR entero, no de una conexión.
- **1 hilo ligero contra 2: sin diferencia concluyente.** Agregando A: 2026 consultas y 427 s de espera;
  agregando B: 2154 consultas y 339 s. La variación entre tramos del mismo tipo (A1 contra A2) es tan grande como
  la diferencia entre tipos (el primer tramo fue el peor). Ninguna configuración causó fallos ni afectó a las
  descargas. Se deja `LIGHT_THREADS = 2`.
- El DVR quedó sano al terminar.
- Nota de método: al lanzarla se colaron 2 copias unos 20 s (4 descargas simultáneas); se detuvieron, se
  comprobó el DVR (sano) y se reinició desde cero; esos segundos no cuentan en la tabla.

## Adenda 6 (2026-09-19): 4 transmisiones en vivo + descargas de clips a la vez

Hasta hoy nunca se había medido la combinación (la regla "no mezclar grabaciones con vivo" era una precaución). Prueba escalonada, app
cerrada: 4 canales RTSP (substream, aperturas con 1.5 s de separación, como la app) abiertos todo el tiempo, y encima descargas por
el `RecordingDownloadManager` (pausa de 1 s), con consultas de salud cada 0.5 s. Se corta a la primera anomalía.

| Prueba | Vivo (fps por canal / hueco máx) | Descargas | Consultas de salud |
|---|---|---|---|
| 4 en vivo solas, 60 s | 15.0 / 0.1 s | — | 105, mediana 70 ms, máx 0.1 s |
| + 1 descarga de 45 s, 60 s | 15.0 / 0.1 s | 35 ok, 0 fallos, 1.7 s c/u | 96, máx 2.3 s |
| + 2 descargas de 45 s, 119 s | 14.5 / 0.1 s | 26 ok, **2 fallos**, **8.3 s c/u** | 55, mediana 140 ms, **máx 31.4 s** (4 > 3 s) |
| 4 en vivo + 1 descarga de 5 min, 295 s | 14.9 / 0.1 s | 22 ok, **2 fallos**, 12.2 s c/u | 372, máx 30.8 s (5 > 3 s) |

- **El vivo nunca se afectó**: ninguna reconexión, ningún hueco > 0.1 s, en ninguna de las pruebas. El DVR siguió respondiendo consultas
  y con la salud normal al terminar cada una.
- **Lo que sí se degrada son las descargas**: con 2 descargas + vivo tardan 4-5 veces más y fallan; con 1 descarga de trozos de 5 min hubo 2 fallos
  de 24 (sin vivo y con trozos de 45 s, 0 de 616 en la Adenda 5).
- **Controles inconclusos y un efecto secundario**: el control "1 descarga de 5 min SIN vivo" falló en el segundo 1.8 y terminó con la salud
  2/3 (consultas de hasta 59 s), y "4 en vivo + 1 descarga de 60 s" tuvo descargas de 34.7 s de media. El DVR ya venía castigado por las
  pruebas anteriores (~25 minutos seguidos con varios fallos), así que esos dos controles **no son comparables**.
- **DVR degradado después**: consultas y vivo normales (0.06-0.11 s; 20 fps), disco sin errores, pero **una descarga de 5 s (1.3 MB) tarda 22-71 s** en
  cualquier canal y hora (lo normal es < 1 s), incluso tras 5+ minutos sin carga. Antes de estas pruebas, hoy mismo, las descargas tardaban 1-2 s.
  No se puede separar si lo causaron las pruebas o coincidió con un problema propio del DVR; queda pendiente ver si se recupera solo o con reinicio.
- **Conclusión para el diseño**: mezclar descargas con el vivo **no derriba el vivo, pero no es fiable para las descargas**, y con dos a la vez
  degrada el servicio de grabaciones. Se mantiene la regla de pausar las exportaciones durante la vista en vivo.

### Continuación de la Adenda 6: concesión de vista en vivo (2026-09-19, tras reiniciar el DVR)

Con el DVR recuperado (descarga de 5 s: 0.43 s), se implementó en el servicio de descargas la regla "nunca descargas junto al vivo":
`download_service` acepta una **concesión de vivo** (`live_lease`) atada a una conexión abierta (se libera sola si el proceso muere); al pedirla,
`RecordingDownloadManager.acquire_live` deja de arrancar trabajos (siguen en cola, con su orden de prioridad) y espera a los que corrían, incluida su
pausa de cortesía. `DVRClient.start_live` ya no bloquea la interfaz (antes esperaba hasta 35 s en el hilo de la ventana): un hilo aparte toma la
concesión y solo entonces abre los 4 RTSP; al salir del vivo la concesión se suelta tras `LIVE_TO_RECORDINGS_SETTLE` (1.5 s). `download_client.stats()`
informa activas / en cola / concesiones. Reemplaza al antiguo `drain()`.

Validado con el DVR real y la ventana completa (3 ciclos grabaciones → vivo → grabaciones, dos veces):
- `_enter_live()` vuelve en 18-34 ms.
- **0 solapes** entre cualquier descarga y una concesión de vivo, en 62 descargas registradas (6 canceladas por entrar en vivo, 0 fallos reales).
- Una descarga enviada a propósito con el vivo abierto quedó retenida (`terminó = False`, `stats`: en cola 1, concesiones 1) y terminó al volver a grabaciones.
- Los 4 canales tardan ~15 s en estar en vivo (aperturas serializadas con 1.5 s de cortesía + la negociación de cada RTSP); no se cambió aquí. En la Adenda 1 de
  la investigación original, 4 aperturas simultáneas pasaron limpias: la serialización podría relajarse, pendiente de medir.
