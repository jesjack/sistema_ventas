from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import schedule
from .config import REALM
from .digest_auth import NonceStore, parse_authorization, validate_digest_response
from .frames import encode_jpeg, render_frame

STREAM_FPS = 25.0

# El DVR real limita cada llamada a findNextFile a esto, sin importar el
# "count" pedido (verificado contra uno real: pidiendo count=200 devolvio
# 100) -- pero la sesion recuerda hasta donde se quedo, asi que llamadas
# sucesivas siguen entregando paginas hasta agotar resultados. Sin este
# tope el emulador nunca hubiera expuesto el bug real de paginacion visto
# en camera_viewer/dvr_client.py (el codigo cliente comparaba contra el
# "count" pedido en vez de contra "pagina vacia").
REAL_DVR_MAX_RESULTS_PER_CALL = 100

# object_id (de mediaFileFind.cgi) -> clips pendientes de devolver via
# findNextFile. Compartido entre requests/threads, protegido por el lock.
_SESSIONS: dict[str, list[tuple[int, datetime, datetime]]] = {}
_SESSIONS_LOCK = threading.Lock()


class DVRHttpConfig:
    """Config inyectada al handler antes de arrancar el server -- BaseHTTPRequestHandler
    no permite pasar argumentos propios al constructor."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.nonces = NonceStore()


class DVRCgiHandler(BaseHTTPRequestHandler):
    server_version = "DahuaEmulator/1.0"
    protocol_version = "HTTP/1.1"
    dvr_config: DVRHttpConfig  # se asigna en cameras.dvr_emulator.__main__

    def do_GET(self) -> None:  # noqa: N802 (nombre exigido por BaseHTTPRequestHandler)
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        action = query.get("action", [""])[0]

        try:
            handler = self._ROUTES.get(parsed.path)
            if handler is None:
                self._send_text(404, "Not Found\r\n")
                return
            handler(self, action, query)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass  # el cliente (cv2/FFmpeg o requests) corto la conexion antes de tiempo
        except (KeyError, ValueError) as exc:
            self._send_text(400, f"Bad Request: {exc}\r\n")

    # -- autenticacion (Digest, RFC 2617, qop=auth) -----------------------

    def _check_auth(self) -> bool:
        fields = parse_authorization(self.headers.get("Authorization", ""))

        if (
            fields
            and self.dvr_config.nonces.validate_nc(fields.get("nonce", ""), fields.get("nc", ""))
            and validate_digest_response(
                fields,
                method=self.command,
                username=self.dvr_config.username,
                password=self.dvr_config.password,
                realm=REALM,
            )
        ):
            return True

        nonce = self.dvr_config.nonces.issue()
        challenge = f'Digest realm="{REALM}", qop="auth", nonce="{nonce}", opaque="{nonce[:16]}"'
        self.send_response(401)
        self.send_header("WWW-Authenticate", challenge)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    # -- mediaFileFind.cgi -------------------------------------------------

    def _handle_media_file_find(self, action: str, query: dict[str, list[str]]) -> None:
        if action == "factory.create":
            object_id = str(random.randint(10**8, 10**9 - 1))
            with _SESSIONS_LOCK:
                _SESSIONS[object_id] = []
            self._send_text(200, f"result={object_id}\r\n")
            return

        object_id = query.get("object", [""])[0]
        with _SESSIONS_LOCK:
            session_exists = object_id in _SESSIONS

        if not session_exists:
            # Texto literal del DVR real ante un object invalido/vencido.
            self._send_text(200, "Error\r\nBad Request!\r\n")
            return

        if action == "findFile":
            channel = int(query["condition.Channel"][0])
            start_dt = datetime.strptime(query["condition.StartTime"][0], "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(query["condition.EndTime"][0], "%Y-%m-%d %H:%M:%S")
            matches = schedule.find_overlapping_clips(channel, start_dt, end_dt)
            with _SESSIONS_LOCK:
                _SESSIONS[object_id] = [(channel, clip_start, clip_end) for clip_start, clip_end in matches]
            self._send_text(200, "OK\r\n")
            return

        if action == "findNextFile":
            requested = int(query.get("count", ["50"])[0])
            count = min(requested, REAL_DVR_MAX_RESULTS_PER_CALL)
            with _SESSIONS_LOCK:
                pending = _SESSIONS.get(object_id, [])
                batch, _SESSIONS[object_id] = pending[:count], pending[count:]
            self._send_text(200, self._render_find_next_file(batch))
            return

        if action == "destroy":
            with _SESSIONS_LOCK:
                _SESSIONS.pop(object_id, None)
            self._send_text(200, "OK\r\n")
            return

        self._send_text(400, "Bad Request\r\n")

    @staticmethod
    def _render_find_next_file(batch: list[tuple[int, datetime, datetime]]) -> str:
        # Mismos campos que un DVR real (capturado en vivo para comparar):
        # Channel, Cluster, CutLength, Disk, EndTime, FilePath, Flags[0],
        # Length, Partition, StartTime, Type, VideoStream. dvr_client.py
        # solo usa StartTime/EndTime, pero una captura del emulador debe
        # verse igual a una real, no distinguirse por los campos que le
        # faltan o le sobran (el "FileSize" de antes no existe en el real).
        lines = [f"found={len(batch)}"]
        for index, (channel, clip_start, clip_end) in enumerate(batch):
            duration_seconds = int((clip_end - clip_start).total_seconds())
            # ~950MB/hora de video, igual que se veia en los archivos reales.
            length_bytes = int(duration_seconds * (950_000_000 / 3600))
            channel_0indexed = channel - 1
            cluster = random.randint(1000, 99999)
            file_path = (
                f"/mnt/dvr/{clip_start:%Y-%m-%d}/{channel_0indexed:03d}/dav/{clip_start:%H}/0/1/{cluster}/"
                f"{clip_start:%H.%M.%S}-{clip_end:%H.%M.%S}[R][0@0][0].dav"
            )
            lines += [
                f"items[{index}].Channel={channel_0indexed}",
                f"items[{index}].Cluster={cluster}",
                f"items[{index}].CutLength={length_bytes}",
                f"items[{index}].Disk=1",
                f"items[{index}].EndTime={clip_end:%Y-%m-%d %H:%M:%S}",
                f"items[{index}].FilePath={file_path}",
                f"items[{index}].Flags[0]=Timing",
                f"items[{index}].Length={length_bytes}",
                f"items[{index}].Partition=1",
                f"items[{index}].StartTime={clip_start:%Y-%m-%d %H:%M:%S}",
                f"items[{index}].Type=dav",
                f"items[{index}].VideoStream=Main",
            ]
        return "\r\n".join(lines) + "\r\n"

    # -- loadfile.cgi --------------------------------------------------------

    def _handle_loadfile(self, action: str, query: dict[str, list[str]]) -> None:
        if action != "startLoad":
            self._send_text(400, "Bad Request\r\n")
            return

        channel = int(query["channel"][0])
        start_dt = datetime.strptime(query["startTime"][0], "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(query["endTime"][0], "%Y-%m-%d %H:%M:%S")

        if schedule.find_containing_clip(channel, start_dt, end_dt) is None:
            self._send_text(404, "No recording for that range\r\n")
            return

        self._stream_mjpeg(channel, start_dt, end_dt)

    def _stream_mjpeg(self, channel: int, start_dt: datetime, end_dt: datetime) -> None:
        # Real: el DVR manda un contenedor .dav/H264. Aqui: MJPEG-sobre-HTTP
        # generado al vuelo -- cv2.VideoCapture(..., cv2.CAP_FFMPEG) demuxea
        # ambos igual, asi que del lado de la app no hay diferencia.
        #
        # Nota importante sobre el ritmo: esto es lo que _download_recording_chunk
        # de dvr_client.py descarga a un archivo local ANTES de reproducirlo
        # -- _play_chunk vuelve a marcar el ritmo real el desde ese archivo
        # (lee el fps del propio .dav y hace su propio time.sleep). Antes,
        # esta funcion TAMBIEN pausaba entre frame y frame para simular
        # 25fps en tiempo real -- eso duplicaba la espera (cada bloque de
        # 45s tardaba 45s reales solo en DESCARGAR, antes de poder
        # reproducirlo ni un frame), dando la sensacion de que la app se
        # quedaba atorada. Un DVR real manda los bytes del archivo tan
        # rapido como la red lo permita, no a ritmo de reproduccion -- asi
        # que aqui se generan y mandan los frames de corrido, sin pausas.
        # Sin Content-Length (no se sabe de antemano cuantos frames van a
        # salir) y con protocol_version="HTTP/1.1" (keep-alive por
        # defecto), el cliente no tiene NINGUNA forma de saber donde
        # termina esta respuesta salvo que el servidor cierre la conexion
        # -- sin esto, dvr_client.py._download_recording_chunk se queda
        # esperando mas datos para siempre despues del ultimo frame (se
        # verifico: el archivo ya habia dejado de crecer, pero la descarga
        # seguia "colgada"). close_connection=True es lo que le dice al
        # BaseHTTPRequestHandler que cierre el socket al terminar esta
        # respuesta en vez de dejarlo abierto para una siguiente.
        self.close_connection = True

        boundary = "dvrframe"
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        frame_period = 1.0 / STREAM_FPS
        sim_time = start_dt
        caption = f"clip {start_dt:%H:%M:%S} - {end_dt:%H:%M:%S}"

        while sim_time < end_dt:
            payload = encode_jpeg(render_frame(channel, sim_time, caption))
            if payload is None:
                break

            self.wfile.write(
                f"--{boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(payload)}\r\n\r\n".encode("ascii")
            )
            self.wfile.write(payload)
            self.wfile.write(b"\r\n")

            sim_time += timedelta(seconds=frame_period)

    # -- hora / NTP (algo.py, sinc_time.py, check_time.py) -----------------

    def _handle_time_zone(self, action: str, query: dict[str, list[str]]) -> None:
        if action in ("set", "update"):
            self._send_text(200, "OK\r\n")
            return
        self._send_text(400, "Bad Request\r\n")

    def _handle_config_manager(self, action: str, query: dict[str, list[str]]) -> None:
        if action == "getConfig" and query.get("name", [""])[0] == "Time":
            self._send_text(200, f'table.Time="{datetime.now():%Y-%m-%d %H:%M:%S}"\r\n')
            return
        if action == "setConfig":
            self._send_text(200, "OK\r\n")
            return
        self._send_text(400, "Bad Request\r\n")

    def _handle_sysinfo(self, action: str, query: dict[str, list[str]]) -> None:
        if action == "setSystemTime":
            self._send_text(200, "OK\r\n")
            return
        self._send_text(400, "Bad Request\r\n")

    _ROUTES = {
        "/cgi-bin/mediaFileFind.cgi": _handle_media_file_find,
        "/cgi-bin/loadfile.cgi": _handle_loadfile,
        "/cgi-bin/timeZone.cgi": _handle_time_zone,
        "/cgi-bin/configManager.cgi": _handle_config_manager,
        "/cgi-bin/sysinfo.cgi": _handle_sysinfo,
    }

    # -- utilidades ----------------------------------------------------------

    def _send_text(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"[dvr-emulator] {self.address_string()} - {format % args}")
