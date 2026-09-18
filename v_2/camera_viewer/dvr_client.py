from __future__ import annotations

import os
import re
import threading
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import cv2
import requests
from PySide6.QtCore import QObject, Signal
from requests.auth import HTTPDigestAuth

from . import download_client
from .download_manager import DownloadPriority, purge_download_dir

DEFAULT_CHANNELS = (1, 2, 3, 4)
# Puerto del endpoint 'realmonitor' (igual que cameras/vivo.py) -- 554 es
# privilegiado (pide root) y es el que usa el DVR real, pero se puede pisar
# con DVR_RTSP_PORT para que el emulador local corra su servidor RTSP en
# uno normal (ver DVRClient.__init__ y run_camera_viewer_emulated.*).
RTSP_PORT = 554
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

# Cuantas veces se reintenta descargar el MISMO bloque de grabacion antes
# de darlo por perdido.
MAX_CLIP_RETRIES = 3
CLIP_RETRY_BACKOFF = 1.5

# El DVR (Dahua XVR51xxHS-S2, ver camera_viewer/informes/DVR_HARDWARE.md) es un
# equipo de gama baja: un solo SoC embebido generico y un puerto Ethernet
# de 100 Mbps, sin nada en su ficha tecnica que sugiera que su firmware
# esta pensado para atender varias negociaciones de conexion (RTSP+digest,
# o HTTP de loadfile.cgi) al mismo tiempo. En produccion, abrir los 4
# canales a la vez (en vivo o en grabaciones) lo dejaba sin responder por
# completo -- ni siquiera a clientes ajenos a esta app (confirmado con
# curl/nc). Por eso NINGUN intento de conexion nuevo (inicial o reintento,
# de cualquier canal) puede empezar mientras otro este en curso: ver
# DVRClient._open_capture_serialized. Este margen es el tiempo de cortesia
# extra que se espera DESPUES de que un intento concluye (exito o fallo)
# antes de permitir el siguiente -- el DVR puede tardar un instante en
# liberar los recursos de una sesion antes de aceptar otra.
CONNECTION_SERIALIZATION_GAP = 1.5

# Grabaciones: cuantificado en cameras/dvr_stress_test.py y documentado en
# camera_viewer/informes/DVR_STRESS_TEST_RESULTS.md -- el DVR aguanta hasta 3
# sesiones de loadfile.cgi a la vez indefinidamente, pero falla de forma
# reproducible con 4 (sin importar el ancho de banda: se probo tanto a
# maxima velocidad como pausado a ritmo real, con el mismo resultado). Por
# eso la reproduccion de grabaciones NO lee directo del DVR: descarga un
# bloque acotado de video a un archivo local (a traves de
# RecordingDownloadManager, ver download_manager.py, que impone el limite
# de concurrencia hacia el DVR) y lo reproduce desde ahi a ritmo real -- la
# reproduccion en si no toca la red, asi que los 4 canales pueden verse a
# la vez sin nunca superar el limite de conexiones del DVR.
DOWNLOAD_CHUNK_SECONDS = 45.0

# Backpressure de la REPRODUCCION de grabaciones (no de la descarga, que ya
# tiene la suya en download_manager.py): a diferencia de vivo, aqui no se puede descartar
# ningun frame para aliviar presion -- el usuario esta viendo contenido
# grabado especifico, saltarse frames se notaria como huecos/tirones en el
# video. Por eso el freno es "esperar", no "descartar" (ver
# _live_channel_worker para el contraste). Permite hasta este numero de
# frames ya EMITIDOS (encolados hacia Qt o ya en manos de la GUI) sin
# confirmar consumidos todavia; el propio hilo, mientras espera un permiso
# libre, sostiene un frame extra ya decodificado -- en total, como maximo
# hay 3 frames de este canal vivos en memoria a la vez (1 en la GUI + 1 en
# la cola de Qt + 1 esperando turno en el hilo), en vez de crecer sin limite
# si la GUI se atrasa (causa confirmada del congelamiento del sistema, ver
# investigacion de 2026-09-17).
RECORDING_MAX_INFLIGHT_FRAMES = 2
RECORDING_BACKPRESSURE_POLL = 0.2

# Etiqueta de velocidad de reproduccion que se muestra en la esquina de cada
# panel mientras se reproduce una grabacion (ver CameraPanel). Por ahora solo
# existe x1; cuando haya controles de velocidad esto pasa a ser un valor por
# sesion de reproduccion.
PLAYBACK_SPEED_LABEL = "x1"

# Espera antes de la primera descarga al pasar de vivo a grabaciones (ver
# play_from): mismo margen de cortesia que entre conexiones RTSP.
LIVE_TO_RECORDINGS_SETTLE = CONNECTION_SERIALIZATION_GAP

# El DVR limita cada llamada individual a findNextFile a 100 resultados,
# SIN IMPORTAR el "count" que se le pida (se probo pidiendo count=200 y
# devolvio 100) -- pero la sesion (el mismo "object" de findFile) si
# recuerda hasta donde se quedo: la SIGUIENTE llamada a findNextFile trae
# la pagina que sigue con normalidad, y solo cuando ya no queda nada
# devuelve found=0. Verificado directamente contra el DVR real: sobre el
# mismo object, una primera llamada trajo 100 resultados y una segunda
# trajo 28 mas (incluyendo el dia que la primera llamada no alcanzaba).
# El bug real no era un tope de sesion -- era comparar la respuesta contra
# el "count" pedido (200) en vez de contra "vacio": como 100 < 200, el
# bucle se detenia creyendo que ya no habia mas, cuando en realidad
# faltaba pedir una pagina extra.
MAX_RECORDED_DAYS_PAGES = 50


@dataclass(frozen=True)
class Clip:
    channel: int
    start: datetime
    end: datetime


class _Prefetch:
    """Pre-descarga en curso del bloque que sigue al que se esta
    reproduciendo (posiblemente ya en el clip siguiente, incluso del dia
    siguiente). `helper` es el hilo que la prepara cuando primero hay que
    pedir los clips del dia siguiente al DVR."""

    def __init__(self) -> None:
        self.future = None
        self.start: datetime | None = None
        self.helper: threading.Thread | None = None

    def clear(self) -> None:
        self.future = None
        self.start = None


class DVRClient(QObject):
    """Encapsula el protocolo HTTP-CGI del DVR (mediaFileFind.cgi para
    buscar clips, loadfile.cgi para reproducirlos) -- el mismo que ya se
    valido de punta a punta contra cameras/dvr_emulator. Todo el trabajo de
    red/decodificacion corre en hilos aparte; los resultados llegan a la UI
    por señales Qt (seguras entre hilos por diseño de Qt)."""

    clips_ready = Signal(list)          # list[Clip], los 4 canales juntos
    search_failed = Signal(str)
    # Señales separadas para grabaciones y vivo (no una sola compartida):
    # MainWindow tiene un CameraGrid distinto para cada modo, y enrutar por
    # un flag "modo actual" en vez de por el origen de la señal es una
    # condicion de carrera real -- un frame de vivo ya en camino por la red
    # puede llegar justo despues de que el usuario cambie a grabaciones, y
    # con un flag compartido terminaria pintado en el grid equivocado
    # (se vio pasar exactamente esto probando contra el emulador). Con
    # señales separadas el destino lo decide de donde salio el frame, no
    # el estado de la app al momento de llegar.
    recording_frame_ready = Signal(int, object)   # channel, np.ndarray BGR
    recording_channel_status = Signal(int, str)   # channel, texto de estado
    live_frame_ready = Signal(int, object)
    live_channel_status = Signal(int, str)
    # La reproduccion cruzo la medianoche hacia el dia siguiente (lo emite
    # cada canal al pasar; MainWindow ignora los repetidos) -- para que el
    # calendario y la linea de tiempo sigan a la reproduccion.
    playback_day_changed = Signal(object)  # date
    recorded_days_ready = Signal(int, int, set)  # year, month, set[date]
    recorded_days_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Mismos valores por defecto que el resto de cameras/*.py (DVR
        # real). Se pueden pisar con las variables de entorno DVR_HOST /
        # DVR_USER / DVR_PASSWORD / DVR_RTSP_PORT -- asi los scripts
        # run_camera_viewer_emulated.* pueden apuntar la app al emulador
        # local sin tocar la UI, y sin que el resto del tiempo (DVR real)
        # dependa de nada especial en el entorno. Si no estan definidas, se
        # comporta igual que antes.
        self.host = os.environ.get("DVR_HOST", "192.168.1.108")
        self.username = os.environ.get("DVR_USER", "nancy")
        self.password = os.environ.get("DVR_PASSWORD", "miriam.2017")
        self.rtsp_port = int(os.environ.get("DVR_RTSP_PORT", RTSP_PORT))

        self._playback_stop_events: dict[int, threading.Event] = {}
        self._playback_semaphores: dict[int, threading.Semaphore] = {}
        self._playback_threads: list[threading.Thread] = []
        self._playback_session = 0

        self._live_stop_event: threading.Event | None = None
        self._live_threads: list[threading.Thread] = []
        self._live_ready_events: dict[int, threading.Event] = {}

        # Un solo candado para TODO el cliente (vivo) -- ver
        # CONNECTION_SERIALIZATION_GAP arriba. Nunca hay mas de un intento
        # de conexion RTSP nuevo en curso al DVR.
        self._connection_gate = threading.Lock()

        # Las consultas de clips del dia siguiente (ver _prefetch_next_day)
        # las hacen los 4 canales casi a la vez -- se turnan en vez de
        # abrirle al DVR 4 sesiones de mediaFileFind simultaneas.
        self._next_day_fetch_gate = threading.Lock()

        # Las descargas NO se manejan aqui adentro -- ver download_client.py
        # y download_service.py: pasan por un servicio separado (un solo
        # RecordingDownloadManager real, sin importar cuantos procesos
        # distintos le pidan descargas) para que el limite de concurrencia
        # hacia el DVR se respete entre procesos, no solo entre hilos de
        # este.

    def _open_capture_serialized(self, url: str, stop_event: threading.Event) -> cv2.VideoCapture:
        """Abre una conexion (RTSP o HTTP, segun la url) turnandose con
        cualquier otro canal/intento -- ver CONNECTION_SERIALIZATION_GAP.
        cv2.VideoCapture ya es una llamada bloqueante que no vuelve hasta
        que el intento se resuelve (exito o timeout), asi que sostener el
        candado durante la llamada ya garantiza "no empezar el siguiente
        hasta que el anterior haya tenido respuesta"; el wait() de despues
        agrega el margen de cortesia adicional."""
        with self._connection_gate:
            capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            stop_event.wait(CONNECTION_SERIALIZATION_GAP)
            return capture

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

    # -- dias con grabacion (para pintarlos en el calendario) ---------------

    def find_recorded_days(self, year: int, month: int) -> None:
        threading.Thread(target=self._find_recorded_days_worker, args=(year, month), daemon=True).start()

    def _find_recorded_days_worker(self, year: int, month: int) -> None:
        _, last_day = monthrange(year, month)
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, last_day, 23, 59, 59)

        try:
            recorded_days: set[date] = set()
            for channel in DEFAULT_CHANNELS:
                recorded_days |= self._fetch_recorded_dates(channel, start_dt, end_dt)
        except Exception as exc:
            self.recorded_days_failed.emit(str(exc))
            return

        self.recorded_days_ready.emit(year, month, recorded_days)

    def _fetch_recorded_dates(self, channel: int, start_dt: datetime, end_dt: datetime) -> set[date]:
        """Como _fetch_clips, pero solo junta las fechas (sin horarios) de
        inicio de cada clip, pidiendo pagina tras pagina de la MISMA sesion
        hasta que una llamada a findNextFile venga vacia -- ver la nota en
        MAX_RECORDED_DAYS_PAGES sobre por que no basta con revisar si la
        pagina trajo menos de lo pedido."""
        auth = HTTPDigestAuth(self.username, self.password)
        base = f"http://{self.host}/cgi-bin/mediaFileFind.cgi"

        response = requests.get(f"{base}?action=factory.create", auth=auth, timeout=15)
        match = re.search(r"result=(\d+)", response.text)
        if not match:
            raise RuntimeError("No se pudo iniciar la sesion de busqueda en el DVR.")
        object_id = match.group(1).strip()

        dates: set[date] = set()
        try:
            start_query = start_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
            end_query = end_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
            requests.get(
                f"{base}?action=findFile&object={object_id}&condition.Channel={channel}"
                f"&condition.StartTime={start_query}&condition.EndTime={end_query}",
                auth=auth,
                timeout=15,
            )

            for _ in range(MAX_RECORDED_DAYS_PAGES):
                results = requests.get(
                    f"{base}?action=findNextFile&object={object_id}&count=200", auth=auth, timeout=15
                )
                items = self._parse_items(results.text)
                if not items:
                    # Unica señal confiable de que ya no queda nada: el DVR
                    # limita cada llamada a 100 resultados sin importar el
                    # "count" pedido, asi que "menos de lo pedido" NO
                    # significa "es la ultima pagina" -- hay que seguir
                    # pidiendo hasta que de verdad venga vacia.
                    break
                for item in items.values():
                    start = item.get("StartTime")
                    if start:
                        dates.add(datetime.strptime(start.strip(), "%Y-%m-%d %H:%M:%S").date())
        finally:
            try:
                requests.get(f"{base}?action=destroy&object={object_id}", auth=auth, timeout=10)
            except Exception:
                pass

        return dates

    # -- reproduccion -------------------------------------------------------

    def play_from(
        self,
        selected_time: datetime,
        clips_by_channel: dict[int, list[Clip]],
        start_delay: float = 0.0,
    ) -> None:
        """start_delay: espera (cancelable) antes de pedir la primera
        descarga -- se usa al venir de la vista en vivo: los 4 RTSP recien
        cerrados pueden tardar un instante en liberarse del lado del DVR, y
        pedirle descargas de inmediato se parece a abrir sesiones de mas."""
        # Espera a que los hilos de la reproduccion anterior de verdad
        # terminen (join, no un sleep fijo) antes de arrancar los nuevos --
        # si no, un hilo viejo puede intentar emitir una señal justo cuando
        # este objeto ya se esta destruyendo (ver stop_playback/closeEvent).
        self._stop_and_join()
        purge_download_dir()

        self._playback_session += 1
        session_id = self._playback_session
        self._playback_stop_events = {channel: threading.Event() for channel in DEFAULT_CHANNELS}
        self._playback_semaphores = {
            channel: threading.Semaphore(RECORDING_MAX_INFLIGHT_FRAMES) for channel in DEFAULT_CHANNELS
        }
        self._playback_threads = []

        for channel in DEFAULT_CHANNELS:
            channel_clips = clips_by_channel.get(channel, [])
            stop_event = self._playback_stop_events[channel]
            semaphore = self._playback_semaphores[channel]
            thread = threading.Thread(
                target=self._play_channel_worker,
                args=(session_id, channel, selected_time, channel_clips, stop_event, semaphore, start_delay),
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
        self._playback_semaphores = {}
        self._playback_threads = []

    @staticmethod
    def _find_clip(clips: list[Clip], selected_time: datetime) -> Clip | None:
        # Primero el clip donde la hora cae ESTRICTAMENTE antes del final: los
        # clips del DVR son contiguos (02:00-03:00, 03:00-04:00), asi que una
        # hora justo en la frontera coincide con el final de uno y el inicio
        # del siguiente -- devolver el primero (el que termina ahi) dejaba un
        # rango de descarga de largo cero y el canal fallaba con
        # "No se pudo reproducir". El cierre inclusivo solo sirve de respaldo
        # para la ultima marca de un clip sin siguiente.
        for clip in clips:
            if clip.start <= selected_time < clip.end:
                return clip
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

    @staticmethod
    def _next_chunk_target(clips: list[Clip], clip: Clip, chunk_end: datetime) -> tuple[datetime, datetime] | None:
        """Rango [inicio, fin) del bloque que sigue a uno que termina en
        chunk_end: el siguiente del mismo clip, o -- si este era el ultimo --
        el primero del clip adyacente (si ya se conoce)."""
        if chunk_end < clip.end:
            return chunk_end, min(chunk_end + timedelta(seconds=DOWNLOAD_CHUNK_SECONDS), clip.end)
        adjacent = DVRClient._find_adjacent_clip(clips, clip.end)
        if adjacent is None:
            return None
        return adjacent.start, min(adjacent.start + timedelta(seconds=DOWNLOAD_CHUNK_SECONDS), adjacent.end)

    def _submit_prefetch(
        self, channel: int, target: tuple[datetime, datetime], stop_event: threading.Event, prefetch: _Prefetch
    ) -> None:
        prefetch.start = target[0]
        prefetch.future = download_client.submit(
            self.host, self.username, self.password, channel, target[0], target[1],
            DownloadPriority.PREFETCH, stop_event,
        )

    def _prefetch_next_day(
        self,
        channel: int,
        clips: list[Clip],
        clip: Clip,
        stop_event: threading.Event,
        prefetch: _Prefetch,
    ) -> None:
        """Corre en un hilo aparte mientras se reproduce el ULTIMO clip de un
        dia (que termina a medianoche): los clips que conoce el hilo de
        reproduccion son solo los del dia elegido, asi que sin esto al llegar
        a las 00:00 no habia "clip siguiente" y salia "Fin de segmento". Pide
        los clips del dia que sigue y, con ellos, pre-descarga su primer
        bloque igual que en cualquier otra frontera de clip."""
        day_start = clip.end
        day_end = day_start + timedelta(hours=23, minutes=59, seconds=59)
        with self._next_day_fetch_gate:
            if stop_event.is_set():
                return
            try:
                fetched = self._fetch_clips(channel, day_start, day_end)
            except Exception:
                return  # sin clips del dia siguiente: se cae al "Fin de segmento" de siempre
        if stop_event.is_set():
            return
        clips.extend(fetched)
        target = self._next_chunk_target(clips, clip, clip.end)
        if target is not None:
            self._submit_prefetch(channel, target, stop_event, prefetch)

    def _play_channel_worker(
        self,
        session_id: int,
        channel: int,
        selected_time: datetime,
        clips: list[Clip],
        stop_event: threading.Event,
        semaphore: threading.Semaphore,
        start_delay: float = 0.0,
    ) -> None:
        """Reproduce por bloques acotados (DOWNLOAD_CHUNK_SECONDS): cada
        bloque se descarga a un archivo local (a traves del servicio de
        descargas) antes de reproducirlo -- la descarga respeta el limite
        de concurrencia del DVR, la reproduccion en si es local y no cuenta
        contra ese limite.

        Mientras se reproduce un bloque, se adelanta la descarga del
        SIGUIENTE (si sigue en el mismo clip) -- sin esto, cada bloque
        pedia su descarga recien cuando terminaba de reproducirse el
        anterior, y como los 4 canales avanzan casi sincronizados, los 4
        pedian turno casi al mismo instante y se veian pausados a la vez
        cada DOWNLOAD_CHUNK_SECONDS esperando su descarga (reportado
        2026-09-17, ver captura en el hilo de la investigacion). Con la
        pre-descarga, para cuando el bloque actual termina de reproducirse
        el siguiente ya deberia estar listo (o casi) en disco."""
        clip = self._find_clip(clips, selected_time)
        if clip is None:
            self.recording_channel_status.emit(channel, "Sin grabacion en esa hora")
            return

        # Copia propia: _prefetch_next_day le agrega los clips del dia
        # siguiente, y la lista original es la misma que usa MainWindow para
        # dibujar la linea de tiempo del dia elegido.
        clips = list(clips)

        position = max(clip.start, selected_time)
        retries_left = MAX_CLIP_RETRIES
        if start_delay > 0:
            self.recording_channel_status.emit(channel, f"Descargando {position:%H:%M:%S}...")
            if stop_event.wait(start_delay):
                return
        prefetch = _Prefetch()
        next_day_requested = False

        while True:
            if stop_event.is_set() or session_id != self._playback_session:
                return

            chunk_end = min(position + timedelta(seconds=DOWNLOAD_CHUNK_SECONDS), clip.end)

            if prefetch.future is not None and prefetch.start == position:
                future = prefetch.future
            else:
                self.recording_channel_status.emit(channel, f"Descargando {position:%H:%M:%S}...")
                future = download_client.submit(
                    self.host, self.username, self.password, channel, position, chunk_end,
                    DownloadPriority.INTERACTIVE, stop_event,
                )
            prefetch.clear()

            # Adelanta el bloque que SIGUE mientras el actual se reproduce
            # -- dentro del mismo clip, o el primero del clip adyacente si
            # este es el ultimo (sin esto, cada cruce de un clip a otro,
            # p. ej. de una hora a la siguiente, pausaba 2-3 s los canales
            # esperando una descarga; medido 2026-09-18). Se pide recien
            # cuando el bloque actual YA se descargo y empieza a
            # reproducirse (on_playback_start), no junto con el pedido del
            # actual: si se mandaran casi al mismo tiempo (desde hilos
            # distintos, orden de llegada no determinista) la pre-descarga
            # podia llegar primero a una cola vacia y ocupar un hilo
            # descargador, dejando el bloque que el usuario SI esta
            # esperando detras de ella (medido: hasta ~10s de espera).
            def on_playback_start() -> None:
                nonlocal next_day_requested
                target = self._next_chunk_target(clips, clip, chunk_end)
                if target is not None:
                    self._submit_prefetch(channel, target, stop_event, prefetch)
                elif (
                    chunk_end >= clip.end
                    and clip.end.time() == datetime.min.time()
                    and not next_day_requested
                ):
                    # Ultimo clip del dia y no se conoce nada despues: puede
                    # que la grabacion siga en el dia siguiente.
                    next_day_requested = True
                    prefetch.helper = threading.Thread(
                        target=self._prefetch_next_day,
                        args=(channel, clips, clip, stop_event, prefetch),
                        daemon=True,
                    )
                    prefetch.helper.start()

            outcome = self._play_chunk(
                session_id, channel, position, chunk_end, stop_event, semaphore, future, on_playback_start
            )

            if outcome == "stopped":
                return  # detenido por el usuario o cambio de sesion

            if outcome == "error":
                # Fallo al descargar el bloque (o el archivo descargado
                # salio vacio/corrupto) -- descarta cualquier pre-descarga
                # ya en curso (el plan de bloques ya no aplica igual tras
                # un reintento) y reintenta el MISMO bloque antes de darlo
                # por perdido.
                prefetch.clear()
                if retries_left <= 0:
                    self.recording_channel_status.emit(channel, "No se pudo reproducir la grabacion")
                    return
                retries_left -= 1
                self.recording_channel_status.emit(
                    channel, f"Reintentando descarga ({MAX_CLIP_RETRIES - retries_left}/{MAX_CLIP_RETRIES})..."
                )
                if stop_event.wait(CLIP_RETRY_BACKOFF):
                    return
                continue

            # outcome == "ended": este bloque se reprodujo completo.
            retries_left = MAX_CLIP_RETRIES
            position = chunk_end
            if position < clip.end:
                continue  # sigue el mismo clip, siguiente bloque (ya pre-descargandose)

            next_clip = self._find_adjacent_clip(clips, clip.end)
            if next_clip is None and prefetch.helper is not None:
                # Todavia se estaban pidiendo los clips del dia siguiente
                # (normalmente ya termino: tuvo todo el ultimo clip).
                while prefetch.helper.is_alive():
                    if stop_event.is_set() or session_id != self._playback_session:
                        return
                    prefetch.helper.join(0.2)
                next_clip = self._find_adjacent_clip(clips, clip.end)
            if next_clip is None:
                self.recording_channel_status.emit(channel, "Fin de segmento")
                return

            if next_clip.start.date() != clip.start.date():
                self.playback_day_changed.emit(next_clip.start.date())

            clip = next_clip
            position = clip.start

    def _play_chunk(
        self,
        session_id: int,
        channel: int,
        start: datetime,
        end: datetime,
        stop_event: threading.Event,
        semaphore: threading.Semaphore,
        future,
        on_playback_start=None,
    ) -> str:
        """Reproduce [start, end) a partir de `future` -- una descarga ya
        pedida al servicio de descargas (ver download_client.py, que se
        turna con las demas descargas pendientes de cualquier canal, de
        este proceso o de cualquier otro), posiblemente pedida con
        anticipacion mientras se reproducia el bloque anterior (ver
        _play_channel_worker). Devuelve "stopped", "error" o "ended" -- ya
        no hay ambiguedad de "se corto por un corte de red a medias": el
        archivo ya esta completo en disco antes de reproducirlo, asi que
        cualquier fallo durante la reproduccion es un archivo
        vacio/corrupto, no un corte transitorio de la conexion en vivo con
        el DVR."""
        if not future.done():
            # Si ya estaba lista (caso normal gracias a la pre-descarga) no
            # hace falta mostrar "Descargando" -- solo se nota cuando de
            # verdad toca esperar (primer bloque de un clip, o la red no
            # alcanzo a adelantarse dentro de la ventana del bloque previo).
            self.recording_channel_status.emit(channel, f"Descargando {start:%H:%M:%S}...")
        local_path = future.result()

        if stop_event.is_set() or session_id != self._playback_session:
            if local_path is not None:
                local_path.unlink(missing_ok=True)
            return "stopped"
        if local_path is None:
            return "error"

        try:
            capture = cv2.VideoCapture(str(local_path), cv2.CAP_FFMPEG)
            if not capture.isOpened():
                capture.release()
                return "error"

            if on_playback_start is not None:
                on_playback_start()
            # La velocidad no cambia frame a frame -- se avisa una sola vez
            # por bloque (antes se re-emitia la hora en CADA frame, ~30/s por
            # canal, para una etiqueta que repetia la hora que el DVR ya
            # imprime en el video).
            self.recording_channel_status.emit(channel, PLAYBACK_SPEED_LABEL)

            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0 or not fps < float("inf"):
                fps = 25.0
            frame_interval = 1.0 / fps
            next_frame_at = time.monotonic()
            frames_read = 0

            try:
                while True:
                    if stop_event.is_set() or session_id != self._playback_session:
                        return "stopped"

                    now = time.monotonic()
                    if now < next_frame_at:
                        time.sleep(next_frame_at - now)

                    success, frame = capture.read()
                    if not success:
                        break

                    frames_read += 1

                    # Backpressure (ver RECORDING_MAX_INFLIGHT_FRAMES): a
                    # diferencia de vivo, aqui NUNCA se descarta un frame ya
                    # decodificado -- se espera a que la GUI confirme haber
                    # consumido uno anterior (notify_recording_frame_consumed)
                    # antes de emitir este. El poll corto es solo para poder
                    # reaccionar a stop_event/cambio de sesion sin quedar
                    # bloqueado para siempre si el usuario cancela mientras
                    # se espera turno.
                    while not semaphore.acquire(timeout=RECORDING_BACKPRESSURE_POLL):
                        if stop_event.is_set() or session_id != self._playback_session:
                            return "stopped"

                    self.recording_frame_ready.emit(channel, frame)
                    next_frame_at = max(next_frame_at + frame_interval, time.monotonic())
            finally:
                capture.release()

            return "ended" if frames_read > 0 else "error"
        finally:
            local_path.unlink(missing_ok=True)

    # -- vista en vivo (RTSP realmonitor, igual protocolo que cameras/vivo.py) --

    def start_live(self) -> None:
        # Margen amplio (timeout=35: el request de descarga de grabacion
        # tiene su propio timeout de 30s, +5s de sobra) para asegurar de
        # verdad que ningun hilo de reproduccion sigue vivo -- y despues,
        # como garantia final, se confirma que ninguna descarga de
        # grabacion sigue en curso EN NINGUN PROCESO (drena el servicio de
        # descargas por completo) antes de la primera conexion en vivo.
        # Nunca debe haber una sesion de grabacion abierta al mismo tiempo
        # que una de vivo.
        self._stop_and_join(timeout=35.0)
        download_client.drain()
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

    def notify_recording_frame_consumed(self, channel: int) -> None:
        """Equivalente a notify_frame_consumed pero para el freno de
        _play_chunk (ver RECORDING_MAX_INFLIGHT_FRAMES) -- libera un permiso
        del semaforo de ese canal. Si llega tarde (p. ej. un frame que
        quedo encolado en Qt de una sesion de reproduccion ya reemplazada)
        libera un permiso de la sesion NUEVA en su lugar; se tolera porque
        el semaforo no es Bounded (no lanza por exceso) y el peor caso es
        una sesion nueva con un permiso de mas de forma pasajera, nunca un
        crecimiento sin limite."""
        semaphore = self._playback_semaphores.get(channel)
        if semaphore is not None:
            semaphore.release()

    def _live_channel_worker(
        self, channel: int, bare_host: str, stop_event: threading.Event, ready_event: threading.Event
    ) -> None:
        url = (
            f"rtsp://{self.username}:{self.password}@{bare_host}:{self.rtsp_port}"
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
            self.live_channel_status.emit(channel, "Conectando en vivo...")
            capture = self._open_capture_serialized(url, stop_event)

            if capture.isOpened():
                backoff = RECONNECT_BACKOFF_INITIAL  # conexion exitosa: resetea el backoff
                try:
                    while not stop_event.is_set():
                        success, frame = capture.read()
                        if not success:
                            self.live_channel_status.emit(channel, "Se perdio la conexion en vivo")
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
                            self.live_frame_ready.emit(channel, frame)
                            self.live_channel_status.emit(channel, "En vivo")
                finally:
                    capture.release()
            else:
                capture.release()
                self.live_channel_status.emit(channel, "No se pudo conectar en vivo")

            if stop_event.is_set():
                return

            self.live_channel_status.emit(channel, f"Reconectando en {backoff:.0f}s...")
            if stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
