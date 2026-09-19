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
