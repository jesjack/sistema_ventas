from __future__ import annotations

import random
import re
import socket
import subprocess
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from .config import REALM
from .digest_auth import NonceStore, parse_authorization, validate_digest_response
from .frames import FRAME_SIZE, render_frame

LIVE_FPS = 25

_STATUS_TEXT = {
    200: "OK",
    401: "Unauthorized",
    404: "Not Found",
    455: "Method Not Valid in This State",
    461: "Unsupported Transport",
    501: "Not Implemented",
}


class DVRRtspConfig:
    def __init__(self, username: str, password: str, ffmpeg_path: str) -> None:
        self.username = username
        self.password = password
        self.ffmpeg_path = ffmpeg_path
        self.nonces = NonceStore()


class _RTSPRequest:
    __slots__ = ("method", "url", "headers", "cseq")

    def __init__(self, method: str, url: str, headers: dict[str, str]) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.cseq = headers.get("cseq", "0")


def _read_request(sock: socket.socket, buffer: bytearray) -> _RTSPRequest | None:
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buffer.extend(chunk)

    head, _, rest = buffer.partition(b"\r\n\r\n")
    buffer[:] = rest

    lines = head.decode("utf-8", errors="replace").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) < 2:
        return None
    method, url = parts[0], parts[1]

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", "0") or "0")
    while len(buffer) < content_length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer.extend(chunk)
    del buffer[:content_length]

    return _RTSPRequest(method, url, headers)


class RTSPConnectionHandler(threading.Thread):
    """Una conexion TCP RTSP = un hilo. El protocolo es de texto, con varios
    requests seguidos sobre la misma conexion (como HTTP keep-alive)."""

    def __init__(self, sock: socket.socket, addr: tuple[str, int], dvr_config: DVRRtspConfig) -> None:
        super().__init__(daemon=True)
        self.sock = sock
        self.addr = addr
        self.dvr_config = dvr_config
        self.session_id = str(random.randint(10**8, 10**9 - 1))
        self._channel = 1
        self._client_rtp_port: int | None = None
        self._encoder: subprocess.Popen | None = None
        self._feeder_thread: threading.Thread | None = None
        self._stop_feeding = threading.Event()

    def run(self) -> None:
        buffer = bytearray()
        try:
            while True:
                request = _read_request(self.sock, buffer)
                if request is None:
                    break

                if not self._check_auth(request):
                    continue

                if request.method == "OPTIONS":
                    self._handle_options(request)
                elif request.method == "DESCRIBE":
                    self._handle_describe(request)
                elif request.method == "SETUP":
                    self._handle_setup(request)
                elif request.method == "PLAY":
                    self._handle_play(request)
                elif request.method == "TEARDOWN":
                    self._handle_teardown(request)
                    break
                elif request.method == "GET_PARAMETER":
                    self._send_response(request, 200, {}, include_session=True)
                else:
                    self._send_response(request, 501, {}, include_session=False)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self._stop_encoder()
            try:
                self.sock.close()
            except OSError:
                pass

    # -- autenticacion (mismo Digest RFC 2617 que la Fase 1 HTTP) ---------

    def _check_auth(self, request: _RTSPRequest) -> bool:
        fields = parse_authorization(request.headers.get("authorization", ""))

        if (
            fields
            and self.dvr_config.nonces.validate_nc(fields.get("nonce", ""), fields.get("nc", ""))
            and validate_digest_response(
                fields,
                method=request.method,
                username=self.dvr_config.username,
                password=self.dvr_config.password,
                realm=REALM,
            )
        ):
            return True

        nonce = self.dvr_config.nonces.issue()
        challenge = f'Digest realm="{REALM}", qop="auth", nonce="{nonce}"'
        self._send_response(request, 401, {"WWW-Authenticate": challenge}, include_session=False)
        return False

    # -- verbos RTSP -------------------------------------------------------

    def _handle_options(self, request: _RTSPRequest) -> None:
        self._send_response(
            request,
            200,
            {"Public": "OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER"},
            include_session=False,
        )

    def _handle_describe(self, request: _RTSPRequest) -> None:
        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        self._channel = int(query.get("channel", ["1"])[0])

        sdp = (
            "v=0\r\n"
            "o=- 0 0 IN IP4 0.0.0.0\r\n"
            f"s=Canal {self._channel} (emulado)\r\n"
            "c=IN IP4 0.0.0.0\r\n"
            "t=0 0\r\n"
            "m=video 0 RTP/AVP 96\r\n"
            "a=rtpmap:96 H264/90000\r\n"
            "a=fmtp:96 packetization-mode=1\r\n"
            "a=control:trackID=0\r\n"
        ).encode("utf-8")

        self._send_response(
            request,
            200,
            {"Content-Base": request.url + "/", "Content-Type": "application/sdp"},
            body=sdp,
            include_session=False,
        )

    def _handle_setup(self, request: _RTSPRequest) -> None:
        transport_header = request.headers.get("transport", "")
        match = re.search(r"client_port=(\d+)-(\d+)", transport_header)
        if not match:
            self._send_response(request, 461, {}, include_session=False)
            return

        client_rtp_port, client_rtcp_port = int(match.group(1)), int(match.group(2))
        self._client_rtp_port = client_rtp_port

        transport_response = (
            f"RTP/AVP;unicast;client_port={client_rtp_port}-{client_rtcp_port};"
            "server_port=16000-16001"
        )
        self._send_response(request, 200, {"Transport": transport_response})

    def _handle_play(self, request: _RTSPRequest) -> None:
        if self._client_rtp_port is None:
            self._send_response(request, 455, {})
            return

        self._start_encoder(self.addr[0], self._client_rtp_port)
        self._send_response(request, 200, {"Range": "npt=0.000-"})

    def _handle_teardown(self, request: _RTSPRequest) -> None:
        self._stop_encoder()
        self._send_response(request, 200, {})

    # -- encoder H.264 (ffmpeg como subproceso) + empaquetado RTP -----------

    def _start_encoder(self, client_host: str, client_port: int) -> None:
        width, height = FRAME_SIZE
        command = [
            self.dvr_config.ffmpeg_path,
            "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(LIVE_FPS),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-pix_fmt", "yuv420p",
            "-g", str(LIVE_FPS),
            "-payload_type", "96",
            "-f", "rtp",
            f"rtp://{client_host}:{client_port}",
        ]
        self._encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        self._stop_feeding.clear()
        self._feeder_thread = threading.Thread(target=self._feed_frames, daemon=True)
        self._feeder_thread.start()

    def _feed_frames(self) -> None:
        frame_period = 1.0 / LIVE_FPS
        next_at = time.monotonic()
        try:
            while not self._stop_feeding.is_set() and self._encoder is not None and self._encoder.poll() is None:
                now = time.monotonic()
                if now < next_at:
                    time.sleep(next_at - now)

                frame = render_frame(self._channel, datetime.now(), "EN VIVO (emulado)")
                assert self._encoder.stdin is not None
                self._encoder.stdin.write(frame.tobytes())

                next_at += frame_period
        except (BrokenPipeError, OSError):
            pass

    def _stop_encoder(self) -> None:
        self._stop_feeding.set()
        if self._feeder_thread is not None:
            self._feeder_thread.join(timeout=2)
            self._feeder_thread = None

        if self._encoder is not None:
            try:
                if self._encoder.stdin:
                    self._encoder.stdin.close()
            except OSError:
                pass
            self._encoder.terminate()
            try:
                self._encoder.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._encoder.kill()
            self._encoder = None

    # -- utilidades ----------------------------------------------------------

    def _send_response(
        self,
        request: _RTSPRequest,
        status: int,
        headers: dict[str, str],
        body: bytes = b"",
        include_session: bool = True,
    ) -> None:
        lines = [f"RTSP/1.0 {status} {_STATUS_TEXT.get(status, '')}", f"CSeq: {request.cseq}"]
        if include_session:
            lines.append(f"Session: {self.session_id}")
        for key, value in headers.items():
            lines.append(f"{key}: {value}")
        if body:
            lines.append(f"Content-Length: {len(body)}")
        lines.append("")
        lines.append("")

        self.sock.sendall("\r\n".join(lines).encode("utf-8") + body)


class RTSPServer:
    def __init__(self, host: str, port: int, dvr_config: DVRRtspConfig) -> None:
        self.host = host
        self.port = port
        self.dvr_config = dvr_config
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def serve_forever(self) -> None:
        self._listener.bind((self.host, self.port))
        self._listener.listen(8)
        try:
            while True:
                client_sock, addr = self._listener.accept()
                RTSPConnectionHandler(client_sock, addr, self.dvr_config).start()
        finally:
            self._listener.close()
