from __future__ import annotations

import os
import threading
import time
from calendar import monthrange
from concurrent.futures import Future
from datetime import date, datetime

import cv2
from PySide6.QtCore import QObject, Signal

from . import download_client
from .download_manager import purge_download_dir
from .channel_player import ChannelPlayer, PlayerDeps
from .chunk_store import ChunkStore
from .clip import Clip
from .light_query_manager import LightPriority
from .playback_control import PlaybackControl

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
        # Pausa/velocidad/avance de cuadro compartidos por los 4 canales.
        self.control = PlaybackControl(DEFAULT_CHANNELS)
        # Bloques de video ya descargados, compartidos por los 4 reproductores
        # (ver chunk_store.py y channel_player.py).
        self.chunk_store = ChunkStore()

        self._live_stop_event: threading.Event | None = None
        self._live_lease: download_client.LiveLease | None = None
        self._live_lock = threading.Lock()
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

    def search(self, start_dt: datetime, end_dt: datetime, priority: int = LightPriority.USER) -> None:
        threading.Thread(target=self._search_worker, args=(start_dt, end_dt, priority), daemon=True).start()

    def _search_worker(self, start_dt: datetime, end_dt: datetime, priority: int) -> None:
        try:
            futures = {channel: self._submit_find(channel, start_dt, end_dt, 1, priority) for channel in DEFAULT_CHANNELS}
            clips: list[Clip] = []
            for channel, future in futures.items():
                clips.extend(self._clips_from_items(channel, future.result()))
        except Exception as exc:
            self.search_failed.emit(str(exc))
            return

        self.clips_ready.emit(clips)

    def _submit_find(self, channel: int, start_dt: datetime, end_dt: datetime, max_pages: int, priority: int) -> Future:
        """Toda consulta de grabaciones pasa por el carril de consultas
        ligeras del servicio (ver light_query_manager.py), que impone
        prioridades, hilos fijos, timeouts y reintentos."""
        return download_client.find_files(
            self.host,
            self.username,
            self.password,
            channel,
            start_dt,
            end_dt,
            max_pages,
            priority,
            threading.Event(),
        )

    def _fetch_clips(
        self, channel: int, start_dt: datetime, end_dt: datetime, priority: int = LightPriority.USER
    ) -> list[Clip]:
        items = self._submit_find(channel, start_dt, end_dt, 1, priority).result()
        return self._clips_from_items(channel, items)

    @staticmethod
    def _clips_from_items(channel: int, items: list[dict[str, str]]) -> list[Clip]:
        clips: list[Clip] = []
        for item in items:
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
        return clips

    # -- dias con grabacion (para pintarlos en el calendario) ---------------

    def find_recorded_days(self, year: int, month: int) -> None:
        threading.Thread(target=self._find_recorded_days_worker, args=(year, month), daemon=True).start()

    def _find_recorded_days_worker(self, year: int, month: int) -> None:
        _, last_day = monthrange(year, month)
        start_dt = datetime(year, month, 1)
        end_dt = datetime(year, month, last_day, 23, 59, 59)

        try:
            # Se piden todas las paginas hasta que una venga vacia -- ver la
            # nota en MAX_RECORDED_DAYS_PAGES sobre por que no basta con
            # revisar si la pagina trajo menos de lo pedido.
            futures = [
                self._submit_find(channel, start_dt, end_dt, MAX_RECORDED_DAYS_PAGES, LightPriority.USER)
                for channel in DEFAULT_CHANNELS
            ]
            recorded_days: set[date] = set()
            for future in futures:
                for item in future.result():
                    start = item.get("StartTime")
                    if start:
                        recorded_days.add(datetime.strptime(start.strip(), "%Y-%m-%d %H:%M:%S").date())
        except Exception as exc:
            self.recorded_days_failed.emit(str(exc))
            return

        self.recorded_days_ready.emit(year, month, recorded_days)

    # -- reproduccion -------------------------------------------------------

    def play_from(
        self,
        selected_time: datetime,
        clips_by_channel: dict[int, list[Clip]],
        start_delay: float = 0.0,
        paused: bool = False,
    ) -> None:
        """paused: arranca en pausa (muestra solo el primer cuadro de cada canal).
        start_delay: espera (cancelable) antes de pedir la primera
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
        self.control.reset(paused, selected_time)
        self._playback_stop_events = {channel: threading.Event() for channel in DEFAULT_CHANNELS}
        self._playback_semaphores = {
            channel: threading.Semaphore(RECORDING_MAX_INFLIGHT_FRAMES) for channel in DEFAULT_CHANNELS
        }
        self._playback_threads = []

        deps = PlayerDeps(
            store=self.chunk_store,
            control=self.control,
            submit=self._submit_download,
            fetch_clips=self._fetch_next_day_clips,
            emit_frame=self.recording_frame_ready.emit,
            emit_status=self.recording_channel_status.emit,
            emit_day_changed=self.playback_day_changed.emit,
        )
        for channel in DEFAULT_CHANNELS:
            player = ChannelPlayer(
                channel,
                clips_by_channel.get(channel, []),
                deps,
                self._playback_stop_events[channel],
                self._playback_semaphores[channel],
                is_current=lambda session_id=session_id: session_id == self._playback_session,
            )
            thread = threading.Thread(target=player.run, args=(selected_time, start_delay), daemon=True)
            self._playback_threads.append(thread)
            thread.start()

    @property
    def playback_active(self) -> bool:
        """Hay una reproducción en curso (aunque esté en pausa o esperando un salto)."""
        return any(thread.is_alive() for thread in self._playback_threads)

    def seek(self, target: datetime, resume: bool = False) -> None:
        """Salta a `target` SIN reiniciar la reproducción: cada canal busca dentro
        del bloque que ya tiene en disco, o abre el vecino (ver channel_player.py);
        solo descarga si el almacén no lo tiene. resume=True además reanuda si estaba en pausa."""
        if resume and self.control.paused:
            self.control.set_paused(False)
        self.control.request_seek(target)
        if resume:
            self._emit_control_status()

    def _submit_download(self, channel: int, start: datetime, end: datetime, priority: int, stop: threading.Event) -> Future:
        return download_client.submit(self.host, self.username, self.password, channel, start, end, priority, stop)

    def _fetch_next_day_clips(self, channel: int, start: datetime, end: datetime, priority: int) -> list[Clip]:
        # Los 4 canales lo piden casi a la vez: se turnan en vez de abrirle al
        # DVR 4 búsquedas simultáneas.
        with self._next_day_fetch_gate:
            return self._fetch_clips(channel, start, end, priority)

    def stop_playback(self) -> None:
        self._stop_and_join()

    # -- pausa / velocidad / cuadro a cuadro (ver playback_control.py) --------

    def toggle_pause(self) -> bool:
        paused = self.control.toggle_pause()
        self._emit_control_status()
        return paused

    def set_speed(self, speed: float) -> None:
        self.control.set_speed(speed)
        self._emit_control_status()

    def set_reverse(self, reverse: bool) -> None:
        self.control.set_reverse(reverse)
        self._emit_control_status()

    def _emit_control_status(self) -> None:
        """Actualiza la esquina de los canales que YA están mostrando video
        (no pisa un "Descargando…" de un canal que aún espera)."""
        text = self.control.status_text()
        for channel in self.control.playing_channels():
            self.recording_channel_status.emit(channel, text)

    def _stop_and_join(self, timeout: float = 2.0) -> None:
        for event in self._playback_stop_events.values():
            event.set()
        for thread in self._playback_threads:
            thread.join(timeout=timeout)
        self._playback_stop_events = {}
        self._playback_semaphores = {}
        self._playback_threads = []
        self.chunk_store.clear()

    # -- vista en vivo (RTSP realmonitor, igual protocolo que cameras/vivo.py) --

    def start_live(self) -> None:
        """Arranca la vista en vivo sin bloquear a quien llama (la interfaz): un hilo
        aparte toma del servicio de descargas una CONCESIÓN de vivo -- mientras
        dure, ninguna descarga de grabación arranca en ningún proceso, y antes de
        darla espera a que terminen las que ya corren (ver
        download_service._handle_live_lease) -- y solo entonces abre los canales.
        Nunca debe haber una descarga al mismo tiempo que las conexiones en vivo
        (informes/DVR_STRESS_TEST_RESULTS.md, Adenda 6)."""
        # Los hilos de la reproduccion de grabaciones ya deben haber terminado (join,
        # no un sleep fijo); sus descargas pendientes se cancelan al salir.
        self._stop_and_join(timeout=35.0)
        self.stop_live()

        stop_event = threading.Event()
        self._live_stop_event = stop_event
        starter = threading.Thread(target=self._live_starter, args=(stop_event,), name="LiveStarter", daemon=True)
        self._live_threads = [starter]
        starter.start()

    def _live_starter(self, stop_event: threading.Event) -> None:
        lease = download_client.acquire_live_lease(stop_event)
        with self._live_lock:
            if stop_event.is_set():
                if lease is not None:
                    lease.release()
                return
            self._live_lease = lease  # None si el servicio no respondió: se sigue como antes, sin la garantía

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
            with self._live_lock:
                if stop_event.is_set():
                    return
                self._live_threads.append(thread)
            thread.start()

    def stop_live(self, timeout: float = 2.0) -> None:
        if self._live_stop_event is not None:
            self._live_stop_event.set()
        with self._live_lock:
            threads = list(self._live_threads)
        for thread in threads:
            thread.join(timeout=timeout)
        with self._live_lock:
            lease, self._live_lease = self._live_lease, None
            self._live_stop_event = None
            self._live_threads = []
        if lease is not None:
            # Las descargas reanudan tras un margen de cortesía: el DVR tarda un
            # instante en liberar las sesiones RTSP recién cerradas.
            timer = threading.Timer(LIVE_TO_RECORDINGS_SETTLE, lease.release)
            timer.daemon = True
            timer.start()

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
                            self.live_channel_status.emit(channel, "Se perdió la conexión en vivo")
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
