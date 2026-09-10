"""Emulador local del DVR Dahua/Amcrest para probar cameras/*.py sin
depender del DVR real.

Fase 1: protocolo HTTP-CGI -- mediaFileFind.cgi, loadfile.cgi, timeZone.cgi,
configManager.cgi, sysinfo.cgi -- con Digest Auth real (RFC 2617, qop=auth),
igual que el DVR real.

Fase 2: servidor RTSP para el endpoint 'realmonitor' que usa vivo.py.
El handshake RTSP (OPTIONS/DESCRIBE/SETUP/PLAY/TEARDOWN) esta hecho a mano;
la codificacion H.264 real y el empaquetado RTP se delegan a un subproceso
ffmpeg (necesitas tener el binario ffmpeg instalado y accesible).

El video en ambas fases es generado en el momento (no hay grabaciones ni
camaras reales) -- cv2.VideoCapture(..., cv2.CAP_FFMPEG) lo lee igual que
el stream real, asi que del lado de la app no hay diferencia. Cada frame
muestra el canal y la hora superpuestos, para verificar a simple vista que
se esta pidiendo el canal/hora correctos.

Uso:
    python -m cameras.dvr_emulator [--host 0.0.0.0] [--http-port 8080]
                                    [--rtsp-port 554] [--user nancy]
                                    [--password 2409] [--ffmpeg ffmpeg]
                                    [--no-rtsp]

Luego:
  - Grabaciones (dvr_timeline_app.py, dvr_search_app.py, etc.): usa como
    "IP DVR" el host:puerto HTTP (ej. 127.0.0.1:8080) con el mismo usuario/clave.
  - En vivo (vivo.py): cambia su IP_DVR/CANAL o apunta a
    rtsp://usuario:clave@host:puerto-rtsp/cam/realmonitor?channel=N&subtype=0
"""

from __future__ import annotations

import argparse
import shutil
import threading
from http.server import ThreadingHTTPServer

from .config import (
    DEFAULT_FFMPEG_PATH,
    DEFAULT_HOST,
    DEFAULT_HTTP_PORT,
    DEFAULT_PASSWORD,
    DEFAULT_RTSP_PORT,
    DEFAULT_USER,
)
from .http_server import DVRCgiHandler, DVRHttpConfig
from .rtsp_server import DVRRtspConfig, RTSPServer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--rtsp-port", type=int, default=DEFAULT_RTSP_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG_PATH, help="ruta al binario ffmpeg (Fase 2, RTSP)")
    parser.add_argument("--no-rtsp", action="store_true", help="no levantar el servidor RTSP (solo HTTP-CGI)")
    args = parser.parse_args()

    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host

    DVRCgiHandler.dvr_config = DVRHttpConfig(args.user, args.password)
    http_server = ThreadingHTTPServer((args.host, args.http_port), DVRCgiHandler)
    print(f"[dvr-emulator] HTTP-CGI en http://{display_host}:{args.http_port}")
    print(f"[dvr-emulator]   IP DVR = {display_host}:{args.http_port}  usuario = {args.user}  clave = {args.password}")

    rtsp_thread: threading.Thread | None = None
    if not args.no_rtsp:
        if shutil.which(args.ffmpeg) is None:
            print(
                f"[dvr-emulator] Aviso: no se encontro '{args.ffmpeg}' en PATH. "
                "El servidor RTSP arrancara pero PLAY fallara al no poder lanzar el encoder. "
                "Instala ffmpeg o usa --no-rtsp / --ffmpeg <ruta>."
            )
        rtsp_config = DVRRtspConfig(args.user, args.password, args.ffmpeg)
        rtsp_server = RTSPServer(args.host, args.rtsp_port, rtsp_config)
        rtsp_thread = threading.Thread(target=rtsp_server.serve_forever, daemon=True)
        rtsp_thread.start()
        print(f"[dvr-emulator] RTSP (en vivo) en rtsp://{display_host}:{args.rtsp_port}/cam/realmonitor?channel=N&subtype=0")
    else:
        print("[dvr-emulator] RTSP deshabilitado (--no-rtsp)")

    print("[dvr-emulator] Ctrl+C para detener.")

    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http_server.server_close()


if __name__ == "__main__":
    main()
