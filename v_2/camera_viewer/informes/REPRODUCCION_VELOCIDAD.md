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
