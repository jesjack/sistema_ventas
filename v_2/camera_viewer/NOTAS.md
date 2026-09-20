# camera_viewer — notas de traspaso (2026-09-20)

Visor PySide6 de un DVR Dahua (4 canales) dentro del POS. Historial y mediciones: `informes/` y la memoria del proyecto.

## Arquitectura (todo en `v_2/camera_viewer/`)
- **Embudo al DVR** (servicio local por socket, único punto de contacto): `download_manager.py` (2 hilos de descargas, prioridades,
  concesión de vivo), `light_query_manager.py` (2 hilos de consultas CGI), `download_service.py` / `download_client.py`.
- **Reproducción:** `dvr_client.py` (fachada Qt) → un `channel_player.py` por canal (bloques locales en `chunk_store.py`, reversa, saltos).
  `playback_control.py` = reloj compartido + barrera de arranque + límites de rango; sin él los canales se desfasan.
- **UI:** `main_window.py`, `playback_controls.py`, `timeline_widget.py`. **Exportar:** `export_clip.py` (lógica), `export_flow.py`,
  `export_bar.py`, `clip_export_dialog.py` + `clip_timeline.py` (ventana propia). **Info del DVR:** `dvr_info.py` + `dvr_info_dialog.py`.

## Pruebas (no tocan el DVR real)
- Desde `v_2/`: `.venv/bin/python -m unittest camera_viewer.tests.test_<módulo>`; todas juntas ≈ 2 min (232 pruebas), Qt en `offscreen`.
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
- DVR: 3 `loadfile` a la vez van bien, 4 fallan; con el vivo abierto las descargas fallan → concesión de vivo; hay atascos de 6-36 s cada ~70 s.
- Parchear un diálogo de `MainWindow` tras crear `ExportFlow` no surte efecto (guarda el método): parchear `flow._ask_after_seconds`.

## No verificado
- Nada se vio en un monitor real (todo fuera de pantalla): ←/→ frente al calendario, popup "últimos 30 s" con clic real, disposición de la
  ventana de guardado. x1.5 y x2 quedan ~5 % bajo lo pedido (techo medido ≈ x1.9).

## Pendiente
1. Exportar horas/día completo: casillas de horas y canales, sin vista previa, segundo plano con panel (avance, pausa, cancelar), trozos
   unidos con `ffmpeg` (verificar antes la unión de `.dav` en el DVR real), pausa en vivo con `download_client.stats()`, espacio en disco.
2. #3 guardado en segundo plano con la app cerrada (y reanudar tras reiniciar). 3. #9/#9b IA y detección de movimiento (exploratorio).
4. Adelanto más profundo a x1.5/x2 (algunos canales muestran "Descargando…" tras varios saltos). 5. Reversa no cruza a medianoche.
6. Aperturas RTSP serializadas tardan ~15 s en total; el estrés original pasó 4 simultáneas: medir antes de relajar la separación.
7. Zona roja "futura" de la línea de tiempo (el usuario aún no define el problema).
