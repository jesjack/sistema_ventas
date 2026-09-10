from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

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

# Backoff de reconexion (vivo) y reintento de clip (grabaciones): arranca
# en 1s, se duplica en cada fallo consecutivo hasta este tope, y se resetea
# apenas una conexion/lectura tiene exito. Evita mandar al DVR una rafaga
# de reconexiones cuando esta caido o sobrecargado.
RECONNECT_BACKOFF_INITIAL = 1.0
RECONNECT_BACKOFF_MAX = 10.0

# Cuantas veces se reintenta abrir/leer el MISMO clip antes de darlo por
# perdido -- distingue un corte de red transitorio (reintentable) de que la
# grabacion de verdad ya termino.
MAX_CLIP_RETRIES = 3
CLIP_RETRY_BACKOFF = 1.5
# Si la lectura se corta a menos de esto del final esperado del clip, se
# considera un final real (el DVR a veces entrega el archivo un poco corto)
# en vez de un error a reintentar.
CLIP_END_TOLERANCE = timedelta(seconds=2)


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
        retries_left = MAX_CLIP_RETRIES

        while True:
            if stop_event.is_set() or session_id != self._playback_session:
                return

            outcome, resume_time = self._play_single_clip(session_id, channel, start_time, clip.end, stop_event)

            if outcome == "stopped":
                return  # detenido por el usuario o cambio de sesion

            if outcome == "error":
                # Corte de red/timeout transitorio (o fallo al abrir), no el
                # fin real del clip -- reintentar el MISMO clip antes de
                # darlo por perdido, en vez de saltar de inmediato al
                # siguiente segmento (eso descartaria video valido).
                if retries_left <= 0:
                    self.channel_status.emit(channel, "No se pudo reproducir la grabacion")
                    return
                retries_left -= 1
                self.channel_status.emit(
                    channel, f"Reintentando reproduccion ({MAX_CLIP_RETRIES - retries_left}/{MAX_CLIP_RETRIES})..."
                )
                if stop_event.wait(CLIP_RETRY_BACKOFF):
                    return
                start_time = resume_time or start_time
                continue

            # outcome == "ended": el clip SI termino de verdad.
            retries_left = MAX_CLIP_RETRIES
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
    ) -> tuple[str, datetime | None]:
        """Reproduce [start_time, end_time). Devuelve (outcome, resume_time):
        - "stopped": lo corto el usuario o un cambio de sesion (resume_time None).
        - "error": no se pudo abrir, o la lectura se corto muy antes del
          final esperado (corte transitorio) -- resume_time es desde donde
          seguir si se alcanzo a leer algo, o None si no se leyo nada.
        - "ended": el clip de verdad se acabo (resume_time None).
        """
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
            return "error", None

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0 or not fps < float("inf"):
            fps = 25.0
        frame_interval = 1.0 / fps
        next_frame_at = time.monotonic()
        frames_read = 0
        last_frame_time = start_time

        try:
            while True:
                if stop_event.is_set() or session_id != self._playback_session:
                    return "stopped", None

                now = time.monotonic()
                if now < next_frame_at:
                    time.sleep(next_frame_at - now)

                success, frame = capture.read()
                if not success:
                    if frames_read > 0 and last_frame_time >= end_time - CLIP_END_TOLERANCE:
                        return "ended", None
                    return "error", (last_frame_time if frames_read > 0 else None)

                frames_read += 1
                last_frame_time = start_time + timedelta(seconds=frames_read * frame_interval)
                self.frame_ready.emit(channel, frame)
                self.channel_status.emit(channel, f"Reproduciendo {last_frame_time:%H:%M:%S}")
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

        # Reconexion con backoff: un timeout de stream (visto en produccion,
        # ~30s cuando el DVR no aguanta las 4 conexiones a la vez) o un corte
        # de red hacia que capture.read() fallara y el hilo del canal
        # terminara para siempre -- el panel se quedaba congelado en el
        # ultimo frame sin ningun aviso ni forma de recuperarse. Ahora se
        # reintenta indefinidamente mientras stop_event no este puesto.
        backoff = RECONNECT_BACKOFF_INITIAL

        while not stop_event.is_set():
            self.channel_status.emit(channel, "Conectando en vivo...")
            capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

            if capture.isOpened():
                backoff = RECONNECT_BACKOFF_INITIAL  # conexion exitosa: resetea el backoff
                try:
                    while not stop_event.is_set():
                        success, frame = capture.read()
                        if not success:
                            self.channel_status.emit(channel, "Se perdio la conexion en vivo")
                            break

                        # Backpressure: frame_ready cruza al hilo de la GUI
                        # como señal Qt encolada. Sin este freno, si la GUI
                        # no da abasto a renderizar (4 canales a la vez, PC
                        # mas lenta, etc.) la cola de eventos crece sin
                        # limite -- cada frame pendiente es una imagen
                        # completa en memoria. Eso fue justo lo que congelo
                        # la PC en produccion. Aqui se permite como maximo un
                        # frame "en vuelo" por canal: si la GUI no ha
                        # terminado de procesar el anterior, este se
                        # descarta (valido en modo vivo -- nunca es
                        # aceptable acumular).
                        if ready_event.is_set():
                            ready_event.clear()
                            self.frame_ready.emit(channel, frame)
                            self.channel_status.emit(channel, "En vivo")
                finally:
                    capture.release()
            else:
                capture.release()
                self.channel_status.emit(channel, "No se pudo conectar en vivo")

            if stop_event.is_set():
                return

            self.channel_status.emit(channel, f"Reconectando en {backoff:.0f}s...")
            if stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
