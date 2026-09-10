from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import requests
from PySide6.QtCore import QObject, Signal
from requests.auth import HTTPDigestAuth

DEFAULT_CHANNELS = (1, 2, 3, 4)
RTSP_PORT = 554  # puerto fijo del endpoint 'realmonitor' (igual que cameras/vivo.py)
# subtype=1 = substream (baja resolucion) en vez de 0 = stream principal.
# La vista en vivo aqui es una vision general de los 4 canales a la vez, no
# revision detallada de un clip -- no hace falta maxima resolucion, y el
# substream reduce bastante la carga de decodificacion/render por canal.
LIVE_SUBTYPE = 1


@dataclass(frozen=True)
class Clip:
    channel: int
    start: datetime
    end: datetime


class DVRClient(QObject):
    """Encapsula el protocolo HTTP-CGI del DVR (mediaFileFind.cgi para
    buscar clips, loadfile.cgi para reproducirlos) -- el mismo que ya se
    valido de punta a punta contra cameras/dvr_emulator. Todo el trabajo de
    red/decodificacion corre en hilos aparte; los resultados llegan a la UI
    por señales Qt (seguras entre hilos por diseño de Qt)."""

    clips_ready = Signal(list)          # list[Clip], los 4 canales juntos
    search_failed = Signal(str)
    frame_ready = Signal(int, object)   # channel, np.ndarray BGR
    channel_status = Signal(int, str)   # channel, texto de estado

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Mismos valores por defecto que el resto de cameras/*.py (DVR real).
        # Para probar contra el emulador local, cambia el campo "IP DVR" en
        # la UI a 127.0.0.1:8080.
        self.host = "192.168.1.108"
        self.username = "nancy"
        self.password = "miriam.2017"

        self._playback_stop_events: dict[int, threading.Event] = {}
        self._playback_threads: list[threading.Thread] = []
        self._playback_session = 0

        self._live_stop_event: threading.Event | None = None
        self._live_threads: list[threading.Thread] = []
        self._live_ready_events: dict[int, threading.Event] = {}

    # -- busqueda de grabaciones ------------------------------------------

    def search(self, start_dt: datetime, end_dt: datetime) -> None:
        threading.Thread(target=self._search_worker, args=(start_dt, end_dt), daemon=True).start()

    def _search_worker(self, start_dt: datetime, end_dt: datetime) -> None:
        try:
            clips: list[Clip] = []
            for channel in DEFAULT_CHANNELS:
                clips.extend(self._fetch_clips(channel, start_dt, end_dt))
        except Exception as exc:
            self.search_failed.emit(str(exc))
            return

        self.clips_ready.emit(clips)

    def _fetch_clips(self, channel: int, start_dt: datetime, end_dt: datetime) -> list[Clip]:
        auth = HTTPDigestAuth(self.username, self.password)
        base = f"http://{self.host}/cgi-bin/mediaFileFind.cgi"

        response = requests.get(f"{base}?action=factory.create", auth=auth, timeout=15)
        match = re.search(r"result=(\d+)", response.text)
        if not match:
            raise RuntimeError("No se pudo iniciar la sesion de busqueda en el DVR.")
        object_id = match.group(1).strip()

        clips: list[Clip] = []
        try:
            start_query = start_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
            end_query = end_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
            requests.get(
                f"{base}?action=findFile&object={object_id}&condition.Channel={channel}"
                f"&condition.StartTime={start_query}&condition.EndTime={end_query}",
                auth=auth,
                timeout=15,
            )

            results = requests.get(f"{base}?action=findNextFile&object={object_id}&count=200", auth=auth, timeout=15)
            for item in self._parse_items(results.text).values():
                start = item.get("StartTime")
                end = item.get("EndTime")
                if start and end:
                    clips.append(
                        Clip(
                            channel=channel,
                            start=datetime.strptime(start.strip(), "%Y-%m-%d %H:%M:%S"),
                            end=datetime.strptime(end.strip(), "%Y-%m-%d %H:%M:%S"),
                        )
                    )
        finally:
            try:
                requests.get(f"{base}?action=destroy&object={object_id}", auth=auth, timeout=10)
            except Exception:
                pass

        return clips

    @staticmethod
    def _parse_items(payload: str) -> dict[int, dict[str, str]]:
        items: dict[int, dict[str, str]] = {}
        pattern = re.compile(r"items\[(\d+)\]\.([A-Za-z0-9_]+)=(.*)")
        for line in payload.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            items.setdefault(int(match.group(1)), {})[match.group(2)] = match.group(3).strip()
        return items

    # -- reproduccion -------------------------------------------------------

    def play_from(self, selected_time: datetime, clips_by_channel: dict[int, list[Clip]]) -> None:
        # Espera a que los hilos de la reproduccion anterior de verdad
        # terminen (join, no un sleep fijo) antes de arrancar los nuevos --
        # si no, un hilo viejo puede intentar emitir una señal justo cuando
        # este objeto ya se esta destruyendo (ver stop_playback/closeEvent).
        self._stop_and_join()

        self._playback_session += 1
        session_id = self._playback_session
        self._playback_stop_events = {channel: threading.Event() for channel in DEFAULT_CHANNELS}
        self._playback_threads = []

        for channel in DEFAULT_CHANNELS:
            channel_clips = clips_by_channel.get(channel, [])
            stop_event = self._playback_stop_events[channel]
            thread = threading.Thread(
                target=self._play_channel_worker,
                args=(session_id, channel, selected_time, channel_clips, stop_event),
                daemon=True,
            )
            self._playback_threads.append(thread)
            thread.start()

    def stop_playback(self) -> None:
        self._stop_and_join()

    def _stop_and_join(self, timeout: float = 2.0) -> None:
        for event in self._playback_stop_events.values():
            event.set()
        for thread in self._playback_threads:
            thread.join(timeout=timeout)
        self._playback_stop_events = {}
        self._playback_threads = []

    @staticmethod
    def _find_clip(clips: list[Clip], selected_time: datetime) -> Clip | None:
        for clip in clips:
            if clip.start <= selected_time <= clip.end:
                return clip
        return None

    @staticmethod
    def _find_adjacent_clip(clips: list[Clip], previous_end: datetime) -> Clip | None:
        """Busca un clip que continue sin hueco justo despues de
        previous_end -- evita mostrar "Fin de segmento" cuando en realidad
        la grabacion sigue de inmediato en un clip distinto (el DVR parte
        las grabaciones en archivos, pero para el usuario deberia verse
        como una sola reproduccion continua)."""
        for clip in clips:
            if clip.start <= previous_end < clip.end:
                return clip
        return None

    def _play_channel_worker(
        self,
        session_id: int,
        channel: int,
        selected_time: datetime,
        clips: list[Clip],
        stop_event: threading.Event,
    ) -> None:
        clip = self._find_clip(clips, selected_time)
        if clip is None:
            self.channel_status.emit(channel, "Sin grabacion en esa hora")
            return

        start_time = max(clip.start, selected_time)

        while True:
            ended_naturally = self._play_single_clip(session_id, channel, start_time, clip.end, stop_event)
            if not ended_naturally:
                return  # detenido por el usuario, cambio de sesion, o fallo al abrir (ya se emitio el estado)

            next_clip = self._find_adjacent_clip(clips, clip.end)
            if next_clip is None:
                self.channel_status.emit(channel, "Fin de segmento")
                return

            clip = next_clip
            start_time = clip.start

    def _play_single_clip(
        self,
        session_id: int,
        channel: int,
        start_time: datetime,
        end_time: datetime,
        stop_event: threading.Event,
    ) -> bool:
        """Reproduce un segmento [start_time, end_time). Devuelve True si
        termino porque el video se acabo por su cuenta (el llamador intenta
        encadenar un clip contiguo), False si termino por stop_event,
        cambio de sesion, o porque no se pudo abrir."""
        start_query = start_time.strftime("%Y-%m-%d%%20%H:%M:%S")
        end_query = end_time.strftime("%Y-%m-%d%%20%H:%M:%S")
        url = (
            f"http://{self.username}:{self.password}@{self.host}/cgi-bin/loadfile.cgi"
            f"?action=startLoad&channel={channel}&startTime={start_query}&endTime={end_query}"
        )

        self.channel_status.emit(channel, f"Cargando {start_time:%H:%M:%S}")
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            self.channel_status.emit(channel, "No se pudo abrir la grabacion")
            return False

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0 or not fps < float("inf"):
            fps = 25.0
        frame_interval = 1.0 / fps
        next_frame_at = time.monotonic()

        try:
            while True:
                if stop_event.is_set() or session_id != self._playback_session:
                    return False

                now = time.monotonic()
                if now < next_frame_at:
                    time.sleep(next_frame_at - now)

                success, frame = capture.read()
                if not success:
                    return True

                self.frame_ready.emit(channel, frame)
                self.channel_status.emit(channel, f"Reproduciendo {start_time:%H:%M:%S}")
                next_frame_at = max(next_frame_at + frame_interval, time.monotonic())
        finally:
            capture.release()

    # -- vista en vivo (RTSP realmonitor, igual protocolo que cameras/vivo.py) --

    def start_live(self) -> None:
        self._stop_and_join()  # que no quede una reproduccion de grabacion corriendo de fondo
        self.stop_live()

        stop_event = threading.Event()
        self._live_stop_event = stop_event
        self._live_threads = []
        # Un Event de backpressure por canal (ver _live_channel_worker):
        # arranca "set" (listo para el primer frame).
        self._live_ready_events = {channel: threading.Event() for channel in DEFAULT_CHANNELS}
        for ready_event in self._live_ready_events.values():
            ready_event.set()

        bare_host = self.host.split(":")[0]
        for channel in DEFAULT_CHANNELS:
            thread = threading.Thread(
                target=self._live_channel_worker,
                args=(channel, bare_host, stop_event, self._live_ready_events[channel]),
                daemon=True,
            )
            self._live_threads.append(thread)
            thread.start()

    def stop_live(self, timeout: float = 2.0) -> None:
        if self._live_stop_event is not None:
            self._live_stop_event.set()
        for thread in self._live_threads:
            thread.join(timeout=timeout)
        self._live_stop_event = None
        self._live_threads = []

    def notify_frame_consumed(self, channel: int) -> None:
        """La GUI llama esto (desde el hilo principal) justo despues de
        terminar de renderizar un frame -- libera el freno de backpressure
        de _live_channel_worker para ese canal. No hace nada fuera de modo
        vivo (el evento de ese canal puede no existir)."""
        ready_event = self._live_ready_events.get(channel)
        if ready_event is not None:
            ready_event.set()

    def _live_channel_worker(
        self, channel: int, bare_host: str, stop_event: threading.Event, ready_event: threading.Event
    ) -> None:
        url = (
            f"rtsp://{self.username}:{self.password}@{bare_host}:{RTSP_PORT}"
            f"/cam/realmonitor?channel={channel}&subtype={LIVE_SUBTYPE}"
        )

        self.channel_status.emit(channel, "Conectando en vivo...")
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            self.channel_status.emit(channel, "No se pudo conectar en vivo")
            return

        try:
            while not stop_event.is_set():
                success, frame = capture.read()
                if not success:
                    self.channel_status.emit(channel, "Se perdio la conexion en vivo")
                    return

                # Backpressure: frame_ready cruza al hilo de la GUI como
                # señal Qt encolada. Sin este freno, si la GUI no da abasto
                # a renderizar (4 canales a la vez, PC mas lenta, etc.) la
                # cola de eventos crece sin limite -- cada frame pendiente
                # es una imagen completa en memoria. Eso fue justo lo que
                # congelo la PC en produccion. Aqui se permite como maximo
                # un frame "en vuelo" por canal: si la GUI no ha terminado
                # de procesar el anterior, este se descarta (valido en modo
                # vivo -- nunca es aceptable acumular).
                if ready_event.is_set():
                    ready_event.clear()
                    self.frame_ready.emit(channel, frame)
                    self.channel_status.emit(channel, "En vivo")
        finally:
            capture.release()
