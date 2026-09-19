# Velocidad máxima de reproducción de grabaciones (2026-09-19)

Medida con la ventana completa (`MainWindow`, plataforma `offscreen`), los 4 canales reproduciendo
a la vez desde el DVR real (CAM 1 a 960x1080, CAM 2-4 a 1280x720, todos H.264 a 30 fps, ≈ 2.1 Mbps),
pasando por todo el camino real: descarga por el embudo, decodificación con OpenCV, paso a la
interfaz y pintado. Cada velocidad se midió durante 24 s, tras 3 s de calentamiento (equipo de 4 núcleos).
"Velocidad lograda" = cuadros emitidos por canal / (30 fps × segundos).

| Velocidad pedida | Velocidad lograda | CPU del proceso | Esperas de descarga |
|---|---|---|---|
| x1 | 1.00 | 127 % de un núcleo | 0 |
| x1.5 | 1.43 | 203 % | 0 |
| x2 | 1.92 | 283 % | 0 |
| x3 | 1.71-1.75 | 245 % | 2 |
| x4 | 1.59-1.86 | 252 % | 3 |

- **El techo es ≈ x1.9.** Pedir x3 o x4 no acelera nada (incluso baja): el proceso no pasa de ~250 %
  de CPU aunque hay 4 núcleos, lo que apunta a que el cuello es el hilo de la interfaz pintando 4 canales
  (y el GIL de Python), no la decodificación ni la red. No se verificó con un perfilador.
- **x1.5 y x2 quedan ~5 % por debajo** de lo pedido; el cursor de la línea de tiempo avanza a la velocidad
  nominal, así que a x2 se adelanta ~1 s por cada 25 s de video.
- Las descargas aguantan hasta x4 (los bloques de 45 s se consumen en 11 s y el siguiente ya está listo),
  salvo los atascos aislados del DVR.
- Medido fuera de pantalla (sin compositor ni GPU): en un monitor real puede diferir.
- Por eso el botón ofrece **x0.5, x1, x1.5 y x2**.

## Adenda (2026-09-19): saltos dentro del archivo, "no responde" a x2 y el almacén de bloques

**Formato de los archivos del DVR.** Un bloque de 60 s del canal 1 (15.8 MB) es un contenedor `dhav`
(Dahua, no cifrado; `ffprobe` lo lee), un solo flujo H.264 960x1080 a 30 fps, un cuadro clave cada ~1 s y
marcas de tiempo que son la **hora real** (1789812300 = 19/09/2026 10:05:00). Probado con OpenCV 5.0:

| Formato | Saltar por número de cuadro | Saltar por milisegundos | Precisión |
|---|---|---|---|
| `.dav` original | 38-69 ms | 59-848 ms (a veces lento) | exacta (error 0 cuadros) |
| MP4 reempaquetado (`-c copy`, 0.1 s) | 31-54 ms | 30-56 ms | −1 a −9 cuadros |
| MKV reempaquetado (`-c copy`, 0.1 s) | 31-66 ms | 30-58 ms | −7 a −8 cuadros |

Decodificar en secuencia: 330 cuadros/s con conversión a imagen y 859 cuadros/s solo decodificando (`grab()`).
**Conclusión: no conviene convertir los archivos.** El original ya es sin cifrar, y saltar por número de cuadro es
exacto y rápido; el reempaquetado no mejora la velocidad y empeora la precisión.

**"No responde" a x2.** Con la app cerrada, midiendo el retraso de un temporizador de 20 ms en el hilo de la interfaz
con los 4 canales reproduciendo (DVR real): a x1 máx 100 ms; a **x2, 53 avisos en 15 s** (contra 498 en 10 s a x1),
mediana 70 ms y una **parada de 9.9 s**; al volver a x1 se recuperó en ~2 s. Causa: a x2 se pintaban 240 cuadros por segundo
desde un solo hilo. Arreglo: a velocidades altas se decodifican todos los cuadros pero solo se pintan ~30 por segundo por canal
(`DISPLAY_FPS_CAP`; el resto se decodifica con `grab()`, sin convertir).

**Almacén de bloques + saltos sin reiniciar** (`chunk_store.py`, `channel_player.py`): cada canal sirve el video
desde bloques locales y solo descarga lo que falta; tras empezar un bloque trae por adelantado el siguiente (PREFETCH)
y lo de atrás hasta el minuto anterior (BACKGROUND). Un salto llega como orden a los hilos (no se reinician). Bloques: el primero tras un
punto no descargado dura 15 s; los demás terminan en el primer minuto exacto a más de 20 s (20-80 s, 60 s ya alineados);
se conservan 120 s hacia atrás y 200 s hacia adelante.

Comprobado con el DVR real y la ventana completa (fuera de pantalla), tras 20 s de reproducción desde 10:00:20:

| Acción | Primer cuadro por canal | Descargas |
|---|---|---|
| −10 s, −10 s, +10 s, +10 s | 3-33 ms | ninguna bloqueante (todo acierto en el almacén) |
| −10 s en pausa | ~200 ms, sigue en pausa | ninguna |
| clic lejano (10:30:00, 10:00:40) | ~1-3 s | 1 bloque corto de 15 s por canal |
| x2 durante 15 s | 29.6 cuadros/s pintados por canal; retraso máx del bucle de eventos **91 ms**, ningún aviso > 100 ms | — |

Un bloque de 60 s del canal 2 falló dos veces por un tropiezo del DVR (`ConnectionError` tras el reintento del embudo) y se
recuperó al tercer intento (reintento del reproductor).

## Adenda 2 (2026-09-19): reproducción en reversa

H.264 no se puede decodificar hacia atrás, pero el DVR pone un cuadro clave por segundo y OpenCV salta a cualquier cuadro
con precisión exacta. Por eso la reversa decodifica hacia adelante un bloque de 30 cuadros (`REVERSE_BLOCK_FRAMES`) y lo muestra
del último al primero, y mientras tanto va decodificando el bloque anterior a razón de un par de cuadros por cada cuadro
mostrado (mismo hilo del canal). Las descargas miran hacia atrás en espejo: el bloque que termina en la posición actual
(el primero, corto, de 15 s), y el anterior se pide con prioridad PREFETCH; el de adelante queda como BACKGROUND (al revés que en avance).

**Decodificación pura, 4 canales a la vez (sin interfaz), cuadros por segundo por canal:**

| Modo | Cuadros/s por canal |
|---|---|
| Avance (referencia) | 95-109 |
| Reversa, bloque de 12 cuadros | 36 |
| Reversa, bloque de 20 | 58-67 |
| Reversa, bloque de 30 | 70-80 |
| Reversa, bloque de 45 / 60 | 76-85 / 75-95 |

Cada salto de OpenCV decodifica desde el cuadro clave anterior (~15 cuadros de sobra): con bloques chicos ese costo domina.

**Ventana completa contra el DVR real** (reversa con los 4 canales, cruzando fronteras de bloque; retraso del bucle de eventos = temporizador de 20 ms):

| Variante | x1: cuadros pintados/s por canal | x1: retraso máx del bucle | x2: pintados/s | x2: retraso máx |
|---|---|---|---|---|
| Bloque de 12, un solo hilo | 25.0 | 18 ms | 17.7 | 36 ms |
| Bloque de 30, un solo hilo | 26.2 | 29 ms | 22.5 | 22 ms |
| Bloque de 15 + hilo auxiliar (doble búfer) | 29.5 | 538-762 ms | 20.5-23.2 | 1.4-3.9 s |
| **Bloque de 30, siguiente bloque decodificado de a poco (elegida)** | **28.2** | **19 ms** | **25.5** | **165 ms** |

- Con un hilo auxiliar la velocidad llegaba a 29.5 pero la interfaz sufría tirones de hasta ~4 s (compite por CPU con los hilos de los
  canales; bajar su prioridad, limitar los hilos de FFmpeg o cambiar el asignador de memoria no lo arregló). Se descartó.
- La elegida: a x1 se pinta el 94 % del tiempo real (el video se atrasa ~6 % frente al cursor) y a x2 ≈ x1.7 reales, con la interfaz fluida.
- La hora impresa por el propio DVR en el video baja de 10:05:50 a 10:05:46 en 4 s de reloj: retrocede a la velocidad correcta.
- Memoria en reversa: ~2 bloques × 30 cuadros ≈ 180 MB por canal (~700 MB entre los 4) mientras se retrocede.
- A velocidades altas, en reversa solo se convierten a imagen los cuadros que se van a pintar (~30 por segundo); el resto solo se decodifica.

**Hallazgo aparte: los canales no están sincronizados entre sí.** En la captura de la reversa, CAM 2 y CAM 3 marcaban `10:05:40`
cuando CAM 1 y CAM 4 marcaban `10:05:50`. Cada canal arranca cuando termina SU descarga (en esa corrida el DVR tardó ~14 s), y desde
entonces cada uno avanza con su propio reloj: la diferencia del arranque se queda. Ya ocurría en avance.
