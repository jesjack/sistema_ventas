from __future__ import annotations

import itertools
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import PriorityQueue

import requests
from requests.auth import HTTPDigestAuth

# Unico punto de contacto de TODA la app con loadfile.cgi (descarga de
# bloques de grabacion). Nace de la investigacion de 2026-09 (ver
# camera_viewer/informes/): con solo la reproduccion pidiendo descargas ya
# habia que respetar un limite estricto de concurrencia hacia el DVR (ver
# DVR_STRESS_TEST_RESULTS.md -- 3 sesiones de loadfile.cgi a la vez las
# aguanta indefinido, 4 falla de forma reproducible); ese limite se
# imponia con un simple semaforo que cada llamador debia acordarse de
# pedir. Al sumar mas consumidores (pre-descarga para tapar el hueco entre
# bloques, guardado/compresion en segundo plano, exportar un clip para
# conservar) confiar en que CADA llamador pida el semaforo correctamente
# deja de ser prudente -- un solo lugar que se salte el candado (a
# proposito o por un bug) puede volver a tumbar el DVR para todos.
#
# Este modulo es ese unico lugar: el limite de concurrencia queda
# garantizado por CONSTRUCCION (existen exactamente max_concurrent hilos
# descargadores, ni uno mas), no por disciplina de quien llama. Todo pedido
# de descarga, sin excepcion, pasa por RecordingDownloadManager.submit().


DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "runtime" / "camera_viewer_downloads"

# Mismo margen que ya se usaba antes de este modulo (ver
# DVRClient._open_capture_serialized/POST_DOWNLOAD_GAP): cortesia extra
# despues de que una descarga termina, antes de que ese cupo de
# concurrencia se ofrezca al siguiente pedido en cola -- el DVR puede
# tardar un instante en liberar los recursos de una sesion.
POST_DOWNLOAD_GAP = 1.0

# Un ConnectionError ANTES del primer byte (visto en las pruebas de
# 2026-09-18, al final de un atasco del DVR) se reintenta una vez tras esta
# pausa; después del primer byte ya no se reintenta (el archivo está a medias).
DOWNLOAD_RETRY_DELAY = 1.0
ADMISSION_POLL = 0.5  # cada cuánto un hilo detenido por una concesión de vivo revisa si lo cancelaron
MAX_CONCURRENT_DOWNLOADS = 2


class DownloadPriority:
    """Menor numero = mas urgente. Un pedido de prioridad mas alta que
    llega mientras uno de prioridad mas baja sigue EN COLA (todavia no
    arranco) le gana el turno; uno que ya esta EN CURSO no se interrumpe a
    medio descargar (los bloques son chicos y rapidos de bajar, no vale la
    pena la complejidad de un download reanudable todavia)."""

    INTERACTIVE = 0  # alguien esta ESPERANDO este bloque ahora mismo (p. ej. el primer bloque tras elegir una hora)
    PREFETCH = 1  # pre-descarga del siguiente bloque de un canal que ya esta reproduciendo -- nunca debe
    #               ganarle el turno a un INTERACTIVE: sin esta distincion, 4 canales pre-descargando a la vez
    #               (misma prioridad, cola FIFO, solo 2 hilos) dejaban el primer bloque de otro canal hasta
    #               ~10s en cola detras de pre-descargas que nadie estaba esperando todavia
    EXPORT = 2  # el usuario pidio conservar un clip y esta esperando
    BACKGROUND = 3  # guardado/compresion oportunista; nunca debe robarle turno a lo de arriba


@dataclass(order=True)
class _QueueItem:
    priority: int
    seq: int
    job: "_Job" = field(compare=False)


@dataclass
class _Job:
    host: str
    username: str
    password: str
    channel: int
    start: datetime
    end: datetime
    stop_event: threading.Event
    future: Future  # se resuelve con Path (exito) o None (cancelado/error)


class RecordingDownloadManager:
    """Cola de prioridad + un numero FIJO de hilos descargadores
    (`max_concurrent`) que la consumen -- por construccion nunca puede
    haber mas de `max_concurrent` descargas HTTP en curso hacia el DVR al
    mismo tiempo, sin importar cuantos `submit()` distintos se hagan ni
    desde cuantos hilos llamadores.

    No conoce nada de PySide/Qt, de reproduccion, ni de una unica sesion de
    DVRClient en particular -- es deliberadamente un modulo de proposito
    general (recibe host/credenciales/canal/rango de tiempo por PEDIDO, no
    al construirse, entrega una ruta local). Esto es intencional: vive
    dentro de download_service.py (ver ese modulo), un programa APARTE que
    cualquier proceso puede usar -- no puede asumir "las credenciales del
    DVR" como un dato fijo de un solo llamador, cada pedido trae las
    suyas.
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_DOWNLOADS,
        download_dir: Path = DOWNLOAD_DIR,
        post_download_gap: float = POST_DOWNLOAD_GAP,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._download_dir = download_dir
        self._post_download_gap = post_download_gap

        self._queue: PriorityQueue[_QueueItem] = PriorityQueue()
        self._seq_counter = itertools.count()

        # Concesiones de vista en vivo (ver acquire_live): mientras haya al menos
        # una, ningun trabajo nuevo arranca, y quien la pide espera a que los que
        # ya corren terminen (incluida su pausa de cortesia). Esto NO controla la
        # concurrencia en si (eso ya lo garantiza que solo existan max_concurrent
        # hilos): solo separa las descargas de las conexiones RTSP en vivo.
        self._admission = threading.Condition()
        self._live_holders = 0
        self._held = 0  # trabajos ya tomados por un hilo pero detenidos por una concesión de vivo
        self._active = 0  # trabajos en curso (de que se admiten hasta que termina su pausa de cortesia)

        self._workers = [
            threading.Thread(target=self._worker_loop, name=f"RecordingDownloader-{i}", daemon=True)
            for i in range(max_concurrent)
        ]
        for worker in self._workers:
            worker.start()

    def submit(
        self,
        host: str,
        username: str,
        password: str,
        channel: int,
        start: datetime,
        end: datetime,
        priority: int,
        stop_event: threading.Event,
    ) -> Future:
        """Encola un pedido de descarga de [start, end) del canal dado y
        devuelve de inmediato un Future -- no bloquea al llamador. El
        Future se resuelve con la ruta local del archivo descargado, o con
        None si stop_event se activo (antes o durante) o hubo un error de
        red. El llamador decide si reintentar (mismo criterio que antes de
        este modulo: la reproduccion reintenta el mismo bloque)."""
        future: Future = Future()
        job = _Job(
            host=host,
            username=username,
            password=password,
            channel=channel,
            start=start,
            end=end,
            stop_event=stop_event,
            future=future,
        )
        self._queue.put(_QueueItem(priority=priority, seq=next(self._seq_counter), job=job))
        return future

    def acquire_live(self, timeout: float | None = None) -> bool:
        """Concesión de vista en vivo: desde que se pide, NINGÚN trabajo nuevo
        arranca (siguen en cola, con su orden de prioridad) hasta release_live();
        y espera a que terminen los que ya corrían. True = ya no hay ninguna
        descarga en curso, se puede abrir el RTSP. False = venció el tiempo con
        alguna aún en curso (la concesión NO queda tomada). Nunca debe haber una
        descarga de grabación al mismo tiempo que las conexiones en vivo (ver
        informes/DVR_STRESS_TEST_RESULTS.md, Adenda 6: con el vivo abierto las
        descargas fallan y degradan al DVR)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._admission:
            self._live_holders += 1
            while self._active > 0:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    self._live_holders -= 1
                    self._admission.notify_all()
                    return False
                self._admission.wait(remaining)
            return True

    def release_live(self) -> None:
        with self._admission:
            self._live_holders = max(0, self._live_holders - 1)
            self._admission.notify_all()

    def stats(self) -> dict:
        with self._admission:
            return {"active": self._active, "queued": self._queue.qsize() + self._held, "live_holders": self._live_holders}

    def shutdown(self) -> None:
        """Detiene los hilos descargadores (un centinela None por hilo).
        No es indispensable para el ciclo de vida actual de la app (el
        proceso se cierra con os._exit(0), ver MainWindow.closeEvent) pero
        mantiene el modulo utilizable de forma independiente/en pruebas."""
        for _ in self._workers:
            # job=None es el centinela de apagado -- no un _QueueItem(None)
            # suelto, porque PriorityQueue ordena por heapq y comparar
            # directamente None < None revienta. La prioridad no importa
            # para un centinela, pero el campo debe seguir siendo un int.
            self._queue.put(_QueueItem(priority=0, seq=next(self._seq_counter), job=None))
        for worker in self._workers:
            worker.join(timeout=5.0)

    def _worker_loop(self) -> None:
        while True:
            self._wait_no_live()  # con una concesión de vivo activa, los trabajos se quedan en la cola
            item = self._queue.get()
            if item.job is None:
                return
            job = item.job
            with self._admission:
                # Pudo llegar una concesión mientras este hilo esperaba en get().
                self._held += 1
                while self._live_holders > 0 and not job.stop_event.is_set():
                    self._admission.wait(ADMISSION_POLL)
                self._held -= 1
                self._active += 1
            try:
                self._run_job(job)
            finally:
                with self._admission:
                    self._active -= 1
                    self._admission.notify_all()

    def _wait_no_live(self) -> None:
        with self._admission:
            while self._live_holders > 0:
                self._admission.wait(ADMISSION_POLL)

    def _run_job(self, job: _Job) -> None:
        if job.stop_event.is_set():
            job.future.set_result(None)
            return

        url = (
            f"http://{job.host}/cgi-bin/loadfile.cgi"
            f"?action=startLoad&channel={job.channel}"
            f"&startTime={job.start.strftime('%Y-%m-%d%%20%H:%M:%S')}"
            f"&endTime={job.end.strftime('%Y-%m-%d%%20%H:%M:%S')}"
        )
        auth = HTTPDigestAuth(job.username, job.password)

        try:
            local_path = self._download(url, auth, job)
            job.future.set_result(local_path)
        finally:
            # Margen de cortesia: no reabrir un cupo (ni abrir el vivo, ver
            # acquire_live) apenas termina una descarga -- el DVR puede tardar
            # un instante en liberar los recursos de la sesion.
            job.stop_event.wait(self._post_download_gap)

    def _download(self, url: str, auth: HTTPDigestAuth, job: _Job) -> Path | None:
        self._download_dir.mkdir(parents=True, exist_ok=True)
        local_path = self._download_dir / f"ch{job.channel}_{uuid.uuid4().hex}.dav"
        for attempt in range(2):
            wrote_bytes = False
            try:
                with requests.get(url, auth=auth, stream=True, timeout=30) as response:
                    response.raise_for_status()
                    with local_path.open("wb") as fh:
                        for block in response.iter_content(chunk_size=65536):
                            if job.stop_event.is_set():
                                break
                            if block:
                                wrote_bytes = True
                                fh.write(block)
                break
            except requests.exceptions.ConnectionError:
                local_path.unlink(missing_ok=True)
                if wrote_bytes or attempt == 1 or job.stop_event.wait(DOWNLOAD_RETRY_DELAY):
                    return None
            except Exception:
                local_path.unlink(missing_ok=True)
                return None

        if job.stop_event.is_set() or local_path.stat().st_size == 0:
            local_path.unlink(missing_ok=True)
            return None
        return local_path


PURGE_MIN_AGE = 600.0  # segundos: no se toca lo reciente (puede ser una descarga en curso de otro consumidor)


def purge_download_dir(download_dir: Path = DOWNLOAD_DIR, min_age: float = PURGE_MIN_AGE) -> None:
    """Borra archivos temporales de descargas de una corrida anterior (p. ej. si
    la app se cerró de golpe a medio descargar un bloque). Solo los de más de
    `min_age` segundos: los recientes pueden ser una descarga en curso de una
    exportación o de otro proceso, y la reproducción ya limpia sus propios
    bloques (ver ChunkStore.clear)."""
    if not download_dir.exists():
        return
    now = time.time()
    for path in download_dir.glob("*.dav"):
        try:
            if now - path.stat().st_mtime >= min_age:
                path.unlink(missing_ok=True)
        except OSError:
            pass
