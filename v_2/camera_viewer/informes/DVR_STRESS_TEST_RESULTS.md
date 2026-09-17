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
