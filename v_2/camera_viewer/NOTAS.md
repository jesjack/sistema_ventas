# camera_viewer — notas de traspaso (2026-09-20)

Visor PySide6 de un DVR Dahua (4 canales) dentro del POS. Historial y mediciones: `informes/` y la memoria del proyecto.

## Arquitectura (todo en `v_2/camera_viewer/`)
- **Embudo al DVR** (servicio local por socket, único punto de contacto): `download_manager.py` (2 hilos de descargas, prioridades,
  concesión de vivo), `light_query_manager.py` (2 hilos de consultas CGI), `download_service.py` / `download_client.py`.
- **Reproducción:** `dvr_client.py` (fachada Qt) → un `channel_player.py` por canal (bloques locales en `chunk_store.py`, reversa, saltos).
  `playback_control.py` = reloj compartido + barrera de arranque + límites de rango; sin él los canales se desfasan.
- **UI:** `main_window.py`, `playback_controls.py` (iconos de `icons.py`; botones fundidos con `button_group.py`), `timeline_widget.py`. La fila de botones de la ventana principal es una sola: los controles + `ExportBar(compact=True)` incrustada con `set_trailing_widget`; las horas de las marcas se rotulan sobre la línea de tiempo del día (`TimelineWidget.set_marks`). **Exportar:** `export_clip.py` (lógica), `export_flow.py`,
  `export_bar.py`, `clip_export_dialog.py` + `clip_timeline.py` (ventana propia: `ExportBar(window_mode=True)` es su fila superior; las casillas de canal viven en los paneles). **Avance del guardado:** `export_progress.py` (modelo: fases, bytes, velocidad, tiempo restante) + `save_progress_dialog.py` (ventana modal con tarjeta por canal y Cancelar); los bytes salen del servicio con `submit(..., progress=)` y solo se envían a quien los pide. **Info del DVR:** `dvr_info.py` + `dvr_info_dialog.py`. **Exportar horas / día completo:** `export_hours.py` (motor, sin Qt), `hours_progress.py` (modelo), `hours_dialogs.py` (selección + panel de avance), `hours_controller.py` (une todo) y `progress_button.py` (el botón "Exportar" del panel izquierdo, que hace de barra de progreso).
- **Archivador pasivo** (guarda en la PC lo más viejo del DVR, ver más abajo): `archiver.py` (motor, sin Qt: `Archiver.run_once()`/`run_forever()`), `archive_index.py` (índice SQLite: segmentos + cursor por canal), `archive_compactor.py` (recomprime un segmento, GPU con reserva a CPU), `shared_paths.py` (permisos multiusuario de todo lo de `share/`, lo usan también `__main__.py` y `download_service.py`). Punto de entrada propio: `python -m camera_viewer.archiver` (candado de instancia única propio, SIGTERM = parar pronto). `launcher.py` gana `launch_archiver()` (mismo patrón que `launch_detached`); `nucleo/arranque.ejecutar()` lo lanza al abrir el POS (ver Archivador pasivo, más abajo).

## Pruebas (no tocan el DVR real)
- Desde `v_2/`: `.venv/bin/python -m unittest camera_viewer.tests.test_<módulo>`; todas juntas ≈ 3.5 min (498 pruebas), Qt en `offscreen`.
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
- **Registro de tiempos del DVR** (`dvr_log.py`): cada descarga y las consultas lentas/fallidas dejan una línea en `share/logs/camera_viewer/run_*.log` (espera en cola, primer byte, total, intentos, motivo). Primer sitio donde mirar si "los clips tardan". Las descargas CANCELADAS también esperan la pausa de cortesía (antes no: abrían la siguiente sesión al instante y podían pasar de 3).
- DVR: 3 `loadfile` a la vez van bien, 4 fallan; con el vivo abierto las descargas fallan → concesión de vivo; hay atascos de 6-36 s cada ~70 s.
- Parchear un diálogo de `MainWindow` tras crear `ExportFlow` no surte efecto (guarda el método): parchear `flow._ask_after_seconds`.
- **`subprocess.Popen(user=..., group=...)` NUNCA llama a `setgroups()` si no se le pasa también
  `extra_groups`** -- el hijo con privilegios bajados se queda con los grupos SUPLEMENTARIOS de
  root al bifurcar (típicamente ninguno útil), no los del usuario real, aunque su uid/gid
  principal ya sean los suyos. Causa real (encontrada 2026-09-24) de que "VER CAMARAS" no
  funcionara para otro usuario del grupo del negocio: sin su membresía real en `tpv_yaeli`, ese
  usuario no tenía NINGÚN permiso sobre lo que otro ya había creado en `share/runtime`/
  `share/archivo_camaras` (candados, la carpeta de descargas, el archivo de grabaciones), ni su
  propio proceso podía arreglarlo (`chown`/`chmod` a un grupo del que el kernel no lo cree
  miembro -- por eso mis propias verificaciones del día anterior, hechas como `jesjack`
  DIRECTO, sin pasar por este camino, no lo habían notado). Arreglado en
  `launcher._drop_privileges_kwargs()` con `extra_groups=os.getgrouplist(usuario, gid)`.
  Si esto vuelve a pasar: revisar `share/runtime` y `share/archivo_camaras` a mano
  (`stat -c '%A %U:%G %n'`) -- lo creado ANTES del arreglo se quedó con el grupo del usuario
  que lo creó primero, no `tpv_yaeli`, y hay que corregirlo una vez a mano (`chgrp -R`).
- **`share/` (la carpeta compartida del POS) trae una ACL POSIX por defecto heredable de "rwx para cualquiera"** (para Samba, `getfacl -p share` lo muestra: `default:other::rwx`). Un `mkdir`/`open` normal ahí abajo HEREDA esa ACL sin importar el `chmod` ni el `umask` del proceso -- una grabación guardada a mano ahí habría quedado legible/escribible por cualquier usuario del sistema, no solo por `tpv_yaeli` (encontrado y corregido el 2026-09-23 al aterrizar el primer segmento real: el `.dav` salió `-rw-rw-rw-`). `shared_paths.ensure_shared_root()` la quita con `setfacl -b`; cualquier carpeta nueva bajo `share/` debe pasar por ahí (o por una ya "curada" por ella), nunca un `Path.mkdir()` suelto.

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

## Archivador pasivo: más allá de lo que guarda el DVR (empezado 2026-09-23)

Idea del usuario: el DVR solo guarda ~6 días (medido: canal 1 iba de 2026-09-16 13:00 a "ahora" el
día 21); en vez de duplicar lo reciente, la PC copia SOLO lo más viejo -- lo que el DVR está a punto
de sobrescribir -- así los dos rangos se SUMAN en vez de solaparse. Se apaga siempre que el negocio
cierra (todas las noches y los domingos), así que el margen de seguridad son 3 días (cubre un cierre
de viernes noche a lunes). Guarda en `share/archivo_camaras/` (no en `runtime/`, que también se movió
a `share/runtime/`: así CUALQUIER usuario del grupo `tpv_yaeli` puede correr la app y el archivador
sin ser root ni el mismo usuario que lo usó la primera vez -- ver `shared_paths.py` y la trampa de la
ACL de `share/` arriba).

**Cómo decide qué bajar** (`archiver.py`, sin Qt): para cada canal se pregunta al DVR real (no un
número fijo) cuál es su grabación más vieja (`_dvr_oldest`, refrescado cada 30 min) y nunca se
archiva más allá de `dvr_oldest + margin_days` (3 por omisión) -- ese es el colchón. Un cursor por
canal (`archive_index.get_cursor`/`set_cursor`, en el índice, no en memoria) recuerda hasta dónde se
revisó, avance haya habido grabación o no: un hueco real (cámara apagada un rato) se salta sin
preguntar lo mismo para siempre; una consulta que FALLA no mueve el cursor (se reintenta). Aterriza
en trozos de 5 min, un solo trozo en vuelo, prioridad `DownloadPriority.ARCHIVE` (la más baja de
todas: nunca le roba turno a la reproducción, los clips cortos ni exportar horas) más un tope propio
de 30 Mbps (defensivo: con prioridad+un solo flujo ya casi no hace falta, ver medición abajo). Un
segundo paso, más despacio, compacta lo aterrizado (`archive_compactor.py`): recomprime con GPU
(VAAPI H.264, reserva a CPU x264 si falla o no hay GPU), fotograma clave cada 4 s (por TIEMPO, no
por cuadros: los canales no van todos a los mismos fps) para poder recortar sin recodificar en
cualquier segmento de ~4 s. Presupuesto de disco (500 GB máximo / 150 GB libres mínimo por omisión):
al pasarse, se desaloja el segmento más viejo de TODO el archivo (cualquier canal).

**Medido en el DVR real (2026-09-21/23, canal 1):**
- Un solo flujo sostenido: ~51 Mbps durante 100 s sin ninguna anomalía (ni siquiera atascó las
  consultas ligeras, que se midieron sanas todo el tiempo); igual con un tope de 50 Mbps. Un día
  completo de 1 canal (~23 GB) tardaría ~1 h a ese ritmo; los 4 canales (~91 GB/día), ~4 h.
- Recomprimir por GPU (qp30, calidad media): 3 muestras de los 4 canales a 3 horas del día (incluida
  la madrugada) dieron 5-30x menos peso según cuánto se mueve la escena (el DVR graba a bitrate FIJO
  gaste o no gaste eso en algo que cambió de verdad), sin pérdida visible comparando recortes lado a
  lado. qp34 ahorra más (hasta 30x) pero ya se nota algo más suave en texturas finas; qp26 casi no
  pierde nada pero ahorra menos (~5x). `archive_compactor.QUALITY_LOW/MEDIUM/HIGH`.
- Recortar un archivo con fotograma clave cada 4 s (`-c copy`, sin recodificar) SÍ empieza en el
  cuadro del fotograma clave anterior, no en el punto exacto pedido (esperable: sin recodificar,
  cortar solo puede empezar en un cuadro clave) -- por eso LEER/reproducir un tramo compactado debe
  decodificar desde ahí y descartar de más hasta el punto pedido (que es justo lo que ya hace
  `channel_player.py` con los bloques en vivo, no hace falta nada nuevo). Saltar a un segundo
  cualquiera dentro de un archivo comprimido cuesta 46-94 ms, igual que en el `.dav` original.
- Prueba de punta a punta contra el DVR real: aterrizó un segmento de 5 min (79 MB, ch1) en 9.1 s
  (69.8 Mbps) con prioridad `ARCHIVE` correcta en el log; permisos del árbol resultante verificadas
  a mano (`drwxrws---`, grupo `tpv_yaeli`, sin ACL heredada) tras corregir el bug de la ACL de arriba.

**Hecho 2026-09-24: leer del disco antes que del DVR.** `archive_reader.py` (sin Qt):
`lookup()` mira si [start, end) de un canal ya está ENTERO en un solo segmento archivado
(`archive_index.segments_covering` + `find_covering_segment`; si cae a caballo entre dos
segmentos, de momento se pide al DVR como siempre -- unir varios es una mejora futura) y
`extract()` lo recorta con `ffmpeg -c copy` (sin recodificar, rápido) a un archivo nuevo en la
carpeta de descargas de siempre. Enganchado en
`RecordingDownloadManager.submit()` (`download_manager.py`): si hay un acierto, se sirve en un
hilo APARTE de los `max_concurrent` de descarga (no consume cupo, no espera concesión de vivo
ni la pausa de cortesía -- nada de eso protege al DVR de algo que nunca lo toca) y, si la
extracción fallara por lo que sea, la MISMA llamada sigue con el pedido real al DVR (nunca hace
falta que quien llama reintente). `archive_dir` es `None` por omisión en la clase (para que
ninguna prueba toque sin querer el archivo real de la máquina, que sigue creciendo con el uso
real del POS) -- `download_service.py` es el único que le pasa la carpeta real
(`shared_paths.ARCHIVE_DIR`, movida ahí desde `archiver.py` para evitar un import circular:
`download_manager -> archive_reader -> export_clip -> download_manager` si `find_ffmpeg` se
hubiera importado de `export_clip.py` en vez de reimplementarse en 2 líneas).
Prueba real: un minuto de un canal ya archivado (2026-09-18, canal 1) se sirvió en 0.22 s
(contra varios segundos de ida y vuelta al DVR), con 59.97 s de duración real. Todo consumidor
(reproducción, guardar clip, exportar horas, el propio archivador) se beneficia sin que se le
haya tocado una sola línea: pasa por `download_client.submit()` -> `download_manager.submit()`
igual que siempre.

**Falta:**
1. **Unir segmentos cuando el rango pedido cae a caballo entre dos** (hoy: si no hay UNO solo
   que lo cubra entero, se pide al DVR aunque los datos ya estén, repartidos, en la PC).
2. **Calendario y línea de tiempo:** que muestren también los días que solo están en la PC (hoy solo
   preguntan al DVR).
3. **Selección inteligente** (por horario del negocio, y si el DVR expone algo de movimiento): lo que
   convierte esto en el "x2/x3" de capacidad que se estimó con el usuario.
4. ~~Arrancarlo con el POS~~ **hecho 2026-09-23:** `nucleo/arranque.ejecutar()` lo lanza justo tras
   `asegurar_instancia_unica()` (así corre mientras el POS esté abierto, en los dos modos, no solo
   con "VER CAMARAS") vía `camera_viewer.launcher.launch_archiver()` (nueva, junto a
   `launch_detached`: mismo patrón -- proceso aparte en el venv de camera_viewer, privilegios
   bajados si el POS corre por sudo, log propio en `share/logs/camera_viewer/archiver_run_*.log`) y lo
   cierra con `atexit` (`archiver.py` atiende SIGTERM con `Archiver.request_stop()`, así no deja un
   trozo a medias). Import LOCAL en `arranque.py` (no arriba del archivo): ese módulo corre en el
   Python embebido de LibreOffice, que no tiene OpenCV -- `camera_viewer.launcher` sí puede
   importarse ahí (solo biblioteca estándar), `camera_viewer.archiver` NO.
   **`nucleo/arranque.py` (y todo `nucleo/`, `tests/`, etc.) sigue SIN COMMITEAR** -- es el
   refactor de la otra instancia (memoria: "POS refactor 2026-09-21"), en el árbol de trabajo desde
   entonces. Mis ~30 líneas ahí (más `tests/test_archivador_arranque.py`, nuevo) quedaron
   sin commitear A PROPÓSITO junto con ese refactor, para no ser quien decide cuándo se commitea
   el trabajo de otra instancia: viajan ya integradas en el árbol, listas para cuando se commitee
   `nucleo/`.
5. **Solo probado con el DVR real un aterrizado suelto de un canal**, nunca `run_forever()` corriendo
   un rato largo, ni con los 4 canales a la vez, ni la pausa por vista en vivo REAL (solo con DVR
   falso), ni el desalojo por presupuesto con datos de verdad, ni el arranque/cierre real desde el
   POS (sí con dobles: `tests/test_archivador_arranque.py`, y `LauncherEnvTests` en
   `camera_viewer/tests/test_export_folder.py`).

## Pendiente (lo de antes)
1. (hecho) Exportar horas. 2. (empezado arriba) Archivador pasivo -- falta leer del disco, calendario, selección inteligente, arrancarlo con el POS.
3. #9/#9b IA y detección de movimiento (exploratorio; ver selección inteligente arriba).
4. Adelanto más profundo a x1.5/x2 (algunos canales muestran "Descargando…" tras varios saltos). 5. Reversa no cruza a medianoche.
6. Aperturas RTSP serializadas tardan ~15 s en total; el estrés original pasó 4 simultáneas: medir antes de relajar la separación.
7. Zona roja "futura" de la línea de tiempo (el usuario aún no define el problema).
