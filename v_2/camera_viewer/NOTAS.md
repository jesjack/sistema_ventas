# camera_viewer — notas de traspaso (2026-09-20)

Visor PySide6 de un DVR Dahua (4 canales) dentro del POS. Historial y mediciones: `informes/` y la memoria del proyecto.

## Arquitectura (todo en `v_2/camera_viewer/`)
- **Embudo al DVR** (servicio local por socket, único punto de contacto): `download_manager.py` (2 hilos de descargas, prioridades,
  concesión de vivo), `light_query_manager.py` (2 hilos de consultas CGI), `download_service.py` / `download_client.py`.
- **Reproducción:** `dvr_client.py` (fachada Qt) → un `channel_player.py` por canal (bloques locales en `chunk_store.py`, reversa, saltos).
  `playback_control.py` = reloj compartido + barrera de arranque + límites de rango; sin él los canales se desfasan.
- **UI:** `main_window.py`, `playback_controls.py` (iconos de `icons.py`; botones fundidos con `button_group.py`), `timeline_widget.py`. La fila de botones de la ventana principal es una sola: los controles + `ExportBar(compact=True)` incrustada con `set_trailing_widget`; las horas de las marcas se rotulan sobre la línea de tiempo del día (`TimelineWidget.set_marks`). **Exportar:** `export_clip.py` (lógica), `export_flow.py`,
  `export_bar.py`, `clip_export_dialog.py` + `clip_timeline.py` (ventana propia: `ExportBar(window_mode=True)` es su fila superior; las casillas de canal viven en los paneles). **Avance del guardado:** `export_progress.py` (modelo: fases, bytes, velocidad, tiempo restante) + `save_progress_dialog.py` (ventana modal con tarjeta por canal y Cancelar); los bytes salen del servicio con `submit(..., progress=)` y solo se envían a quien los pide. **Info del DVR:** `dvr_info.py` + `dvr_info_dialog.py`. **Exportar horas / día completo:** `export_hours.py` (motor, sin Qt), `hours_progress.py` (modelo), `hours_dialogs.py` (selección + panel de avance), `hours_controller.py` (une todo) y `progress_button.py` (el botón "Exportar" del panel izquierdo, que hace de barra de progreso).

## Pruebas (no tocan el DVR real)
- Desde `v_2/`: `.venv/bin/python -m unittest camera_viewer.tests.test_<módulo>`; todas juntas ≈ 2 min (398 pruebas), Qt en `offscreen`.
- Los DVR falsos generan video sintético; OpenCV no puede ESCRIBIR `.dav` (crear `.avi` y renombrar).

## Validar con el DVR real (IP 192.168.1.108)
1. App cerrada (`ps -eo pid,args | grep [c]amera_viewer`) y una descarga de 5 s de `loadfile.cgi` que tarde < 2 s; si tarda más, reiniciar el DVR.
2. Escalonar y cortar a la primera anomalía; nunca pruebas de estrés seguidas (una racha lo degradó hasta reiniciarlo).
3. Lanzar con `setsid nohup`, esperar por PID (no `pgrep -f`, se encuentra a sí mismo) y guardar salida en un archivo con marcador `FIN`.

## Trampas conocidas
- `MainWindow.closeEvent` termina con `os._exit(0)`: en pruebas jamás `w.close()` (parchear `main_window.os._exit`).
- Los hilos nunca deben referenciar widgets/QObject (el último dueño lo destruye fuera del hilo GUI: "Bus error"); usar cola + `QTimer`.
- El POS corre como root y baja solo uid/gid: `launcher.py` debe fijar HOME (ya lo hace). No usar `$HOME`/`Path.home()`; ver `export_clip.user_home()`.
- `PlaybackControl.wait_turn` devuelve "seek" ANTES de esperar el reloj (atender el salto es lo que avisa "listo": si no, interbloqueo).
- **Registro de tiempos del DVR** (`dvr_log.py`): cada descarga y las consultas lentas/fallidas dejan una línea en `logs/camera_viewer/run_*.log` (espera en cola, primer byte, total, intentos, motivo). Primer sitio donde mirar si "los clips tardan". Las descargas CANCELADAS también esperan la pausa de cortesía (antes no: abrían la siguiente sesión al instante y podían pasar de 3).
- DVR: 3 `loadfile` a la vez van bien, 4 fallan; con el vivo abierto las descargas fallan → concesión de vivo; hay atascos de 6-36 s cada ~70 s.
- Parchear un diálogo de `MainWindow` tras crear `ExportFlow` no surte efecto (guarda el método): parchear `flow._ask_after_seconds`.

## No verificado
- Nada se vio en un monitor real (todo fuera de pantalla): ←/→ frente al calendario, popup "últimos 30 s" con clic real, disposición de la
  ventana de guardado. x1.5 y x2 quedan ~5 % bajo lo pedido (techo medido ≈ x1.9).

## Exportar horas (hecho 2026-09-21; medido en el DVR real)
- Un solo flujo baja ≈ 36× el tiempo real (60 s en 2.2 s, 10 min en 16.8 s = 158 MB); con la pausa de cortesía entre trozos y el remux queda ≈ 6 MB/s.
- Trozos consecutivos del DVR: duran justo lo pedido, empiezan en fotograma clave, timestamps absolutos, sin solapes ni huecos → `-c copy` por MPEG-TS y unión con `concat` es exacta.
- Un archivo MP4 por canal. Trozos de 2 min, prioridad `BACKGROUND` y UNO solo en vuelo (siempre queda un cupo libre para reproducción y clips cortos). Huecos de grabación (y trozos perdidos tras 2 reintentos) = tramo negro de `drawtext`, 1 fps, misma resolución del canal, con "Grabación no disponible" y la hora supuesta corriendo.
- La pausa con vista en vivo la hace el embudo (concesión de vivo); el motor solo mira `download_client.stats()` cada 2 s para avisar "Pausado". Con la vista en vivo la exportación espera como mucho un trozo (≈ 5 s). **No se ha probado la pausa con la vista en vivo real, solo con DVR falso.**
- Prueba real (canal 1, 45 min con 3 huecos negros, 3 trozos): 16 s en total, MP4 de 2700.5 s, 7920 paquetes exactos, DTS crecientes. Los avisos "non monotonically increasing dts" al decodificar con `-f null` vienen de los timestamps del `.dav` original, no de la unión.
- Cerrar la app durante una exportación pregunta y cancela (borra sus temporales; los canales ya guardados se conservan).

## Pendiente
1. (hecho arriba) Exportar horas; falta: reanudar tras reiniciar la app y guardado con la app cerrada (siguiente punto).
2. #3 guardado en segundo plano con la app cerrada (y reanudar tras reiniciar). 3. #9/#9b IA y detección de movimiento (exploratorio).
4. Adelanto más profundo a x1.5/x2 (algunos canales muestran "Descargando…" tras varios saltos). 5. Reversa no cruza a medianoche.
6. Aperturas RTSP serializadas tardan ~15 s en total; el estrés original pasó 4 simultáneas: medir antes de relajar la separación.
7. Zona roja "futura" de la línea de tiempo (el usuario aún no define el problema).
