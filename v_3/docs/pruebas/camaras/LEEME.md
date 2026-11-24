# Prueba de cámaras (2026-11-24)

Resultados y reglas del DVR: [`../../camaras_v3.md`](../../camaras_v3.md). **Leer su §1 antes de
correr nada:** máximo 4 sesiones en vivo, abiertas en serie, y `camera_viewer` (v2) cerrado.

- `url_dvr.py <canal> <subtype>`: arma la URL RTSP con las credenciales de `v_2/.env` (no las
  imprime en ningún otro lado; no pasar su salida a un log).
- `prueba_camaras_web.py <cámaras> <subtype> <segundos> <png>`: FFmpeg reempaqueta cada cámara a
  MP4 fragmentado (abre las sesiones en serie, 1.5 s entre una y otra) y una ventana de WebKitGTK
  visible las reproduce; mide CPU y guarda una captura.
- `prueba_gst_decod.py <cámaras> <subtype> <segundos>`: GStreamer nativo, solo decodificar.
  **Ojo:** abre todas las sesiones a la vez (un solo `gst-launch`); usar con 1 cámara o
  escalonar antes de repetirla con 4.
- `webkit_js.py <página> <js> [espera_ms] [png]`: carga una página en WebKitGTK y evalúa JS.

Al terminar, comprobar que no quede nada conectado al DVR:
`ss -tnH state established '( dport = :554 or dport = :80 )' | wc -l` debe dar 0.
