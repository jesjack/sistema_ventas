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
