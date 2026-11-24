# Cámaras en la V3: prueba de video y embudo al DVR (2026-11-24)

Decisión del usuario (P3/P4 de `repaso_decisiones_sin_calc.md`): **las cámaras se integran a la
app, en Rust, como un solo programa**. `camera_viewer` (Python) sigue en la v2 hasta entonces.
Este documento guarda la prueba de cómo mostrar el video y el diseño del embudo al DVR.

## 1. El DVR (resumen de la v2, `v_2/camera_viewer/informes/`)

Dahua **XVR51xxHS-S2**, 4 canales, `192.168.1.108`. Credenciales en `v_2/.env` (`DVR_HOST`,
`DVR_USER`, `DVR_PASSWORD`; fuera del repo). Lo que lo tumba **no es el ancho de banda** sino
negociar varias sesiones nuevas a la vez (queda sin responder a nada hasta reiniciarlo).

| Regla | Valor | Fuente |
|---|---|---|
| Abrir sesiones (RTSP o HTTP) | **una a la vez**, 1.5 s entre una y otra | `DVR_HARDWARE.md`, `dvr_client._open_capture_serialized` |
| Vivo (RTSP, substream) | hasta **4** probado seguro; **más de 4 nunca se probó** | `DVR_STRESS_TEST_RESULTS.md` |
| Descargas `loadfile.cgi` | 3 seguro, 4 falla; la v2 usa **2**, con 1 s de pausa tras cada una | idem |
| Vivo y descargas a la vez | las descargas fallan: **concesión de vivo** | `NOTAS.md` |
| Consultas CGI ligeras | 1–12 a la vez sin fallos (~20 peticiones/s en total); hay atascos intermitentes de 6–36 s | idem, Adenda 2 |
| ¿Está sano? | una descarga de 5 s de `loadfile.cgi` tarda < 2 s; si no, reiniciarlo | `NOTAS.md` |

Flujos: substream (`subtype=1`) **H.264 High 352×240 a 15 cps** (el vivo); principal
(`subtype=0`) **H.264 960×1080 a 30 cps**. URL: `rtsp://…@host:554/cam/realmonitor?channel=N&subtype=S`.

**Incidente de la prueba (2026-11-24), para no repetirlo:** un script de bash lanzó GStreamer con
`eval … &` y guardó el PID del bash intermedio; al "cerrarlo", GStreamer siguió vivo y dejó 5
sesiones RTSP abiertas ~25 min, que con `camera_viewer` abierto sumaron **9** contra el DVR (no
pasó nada visible). Además, `pgrep -af` mostró la línea de comandos con la contraseña. Lecciones:
lanzar procesos sin shell intermedio, comprobar al final que no quede ninguno (`ss` a los puertos
554/80 del DVR), no imprimir argumentos de procesos que llevan la URL, y **ninguna prueba contra
el DVR fuera del embudo**.

## 2. Cómo mostrar el video: medido en la PC de la caja

CPU con 4 cámaras en vivo (substream), 100 % = un núcleo (la PC tiene 4):

| Camino | CPU | Notas |
|---|---|---|
| `camera_viewer` actual (v2, OpenCV) | **15.5 %** | 197 MB, 45 hilos |
| **Vista web**: FFmpeg reempaqueta RTSP → MP4 fragmentado (`-c copy`, sin recodificar) por HTTP local → `<video>` en WebKitGTK | **~18 %** | FFmpeg 0.2 % por cámara; motor web 16.7 %; decodifica por hardware (VA-API) |
| GStreamer nativo (`rtspsrc ! avdec_h264`), solo decodificar | 4.2 % | sin contar el dibujo; por software |

**Decisión propuesta: vista web.** Cuesta casi lo mismo que hoy, toda la interfaz queda en una sola
tecnología y los menús pueden ir encima del video. La reserva, si algún día se usan los flujos
principales o la CPU no alcanza: un elemento GTK con GStreamer nativo encima del webview, en la
misma ventana (una ventana aparte no sirve en Wayland: la app no puede colocarla ni mantenerla
encima de la principal).

Requisitos del sistema (dependencias del instalador): **`gstreamer1.0-plugins-bad`** (sin él
WebKitGTK no reproduce ningún H.264: le falta `h264parse`) y, para decodificar por hardware,
`gstreamer1.0-vaapi` e `intel-media-va-driver`. Instalados en la caja el 2026-11-24.

Pendientes del camino web:
- **Retraso del vivo:** cada `<video>` reproduce desde su primer cuadro y acumula retraso (en la
  prueba, las 4 cámaras mostraban horas distintas, hasta 11 s de diferencia). Hay que mantener la
  reproducción en el borde del búfer (saltar a `buffered.end` cuando se aleja) o usar Media Source
  Extensions con baja latencia.
- **Sin FFmpeg ni contraseña en otro proceso:** el reempaquetado puede hacerse dentro de Rust (un
  cliente RTSP en Rust, p. ej. el crate `retina`, más un empaquetador MP4 fragmentado), así la URL
  con la contraseña no pasa por la línea de comandos de otro proceso y el embudo controla la sesión.
- **Grabaciones:** la v2 descarga bloques `.dav` y los reproduce localmente; en la web habría que
  reempaquetarlos a MP4 (la v2 ya usa FFmpeg para `.dav` → `.mp4`).
- Para probar en WebKit desde scripts: **la ventana debe ser visible**; en una ventana invisible
  (`Gtk.OffscreenWindow`) WebKit no carga video y todo sale en 0.

## 3. El embudo de la v2

`v_2/camera_viewer/`: `download_manager.py` (2 hilos de descargas, cola por prioridad, concesión de
vivo), `light_query_manager.py` (2 hilos de consultas CGI, 3 intentos, tiempos límite
`(5, 35)` s), `download_service.py`/`download_client.py` (servicio aparte por socket local con
clave, candado de instancia única; el primer proceso que lo necesita lo levanta), `dvr_log.py`
(tiempos de cada operación). Pruebas: `tests/test_funnel.py`, `tests/test_live_lease.py`.

El servicio aparte existe porque los límites que viven en la memoria de un proceso no coordinan a
otro: dos procesos con "máximo 2" cada uno suman 4 y tumban el DVR.

## 4. Propuesta: el embudo en Rust

En la v3 todo es un solo programa, así que el embudo puede ser un componente interno (una tarea
asíncrona dueña de todo acceso al DVR), sin socket ni servicio aparte. **Ningún otro código abre
conexiones al DVR**: el tipo `Dvr` no se puede construir fuera del módulo del embudo.

- **API con tipos que garantizan las reglas:**
  - `embudo.vivo(canal) -> Concesion`: abre la sesión RTSP en serie; la sesión dura lo que la
    `Concesion`, y al soltarla (drop) se cierra. Como máximo 4 a la vez. Mientras exista una, no
    arranca ninguna descarga (y antes de concederla se esperan las que estén en curso).
  - `embudo.descargar(canal, rango, prioridad)`: cola por prioridad, máximo 2 en curso, 1 s de
    pausa tras cada una, reintentos.
  - `embudo.consultar(cgi, prioridad)`: carril propio (2 a la vez), reintentos, tiempos límite.
  - `embudo.salud()`: la descarga de prueba de 5 s; el embudo deja de abrir sesiones nuevas y
    avisa en la interfaz si el DVR no responde como debe.
- **Constantes con su fuente:** cada límite apunta al informe de la v2 que lo midió.
- **Registro:** cada operación con espera en cola, primer byte, total, intentos y motivo (como
  `dvr_log.py`), en el log único de la app.
- **Pruebas con un DVR falso** (como los de la v2): el embudo nunca debe pasar de los límites,
  probado sin tocar el DVR real.
- **Convivencia con la v2:** mientras `camera_viewer` (v2) siga en uso, son **dos programas con
  dos embudos** y sus límites se suman. La v3 no debe abrir el DVR si `camera_viewer` está
  abierto: comprobar su candado de instancia única (`share/runtime/`) o el puerto de su servicio
  (51820) antes de conectarse, y avisar.
- **Archivador:** fuera de la V3 por la salud del DVR (decidido en `mapa_v2.md`); si volviera,
  sería otro cliente del mismo embudo, no un proceso aparte.
