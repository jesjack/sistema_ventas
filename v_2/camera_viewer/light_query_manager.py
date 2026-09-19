from __future__ import annotations

import itertools
import re
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from queue import PriorityQueue
from typing import Any, Callable

import requests
from requests.auth import HTTPDigestAuth

# Segundo carril del embudo hacia el DVR (el primero es
# download_manager.py, que solo lleva descargas de clips): consultas
# ligeras (CGI de texto: búsqueda de clips, días con grabación, datos del
# equipo). Diseño acordado el 2026-09-19 a partir de las pruebas de
# informes/DVR_STRESS_TEST_RESULTS.md:
#
#   - Carril propio con LIGHT_THREADS hilos fijos, INDEPENDIENTE del de
#     descargas (2 hilos): nunca se prestan hilos entre carriles, así que
#     hay como máximo 2 + LIGHT_THREADS conexiones a la vez por
#     construcción, y una consulta jamás retrasa el arranque de un clip.
#   - Con descargas activas el DVR atasca las consultas ligeras hasta ~30 s
#     (aun con una sola), así que el timeout de lectura es generoso y cada
#     consulta se reintenta con pausa, cerrando antes la conexión.
#   - Una "consulta" es un trabajo completo (p. ej. la secuencia
#     factory.create/findFile/findNextFile/destroy de mediaFileFind se
#     ejecuta entera en un mismo hilo y se reintenta entera).

LIGHT_THREADS = 2
LIGHT_MAX_ATTEMPTS = 3
LIGHT_RETRY_DELAY = 1.0
LIGHT_TIMEOUT = (5, 35)  # (conectar, leer) en segundos; los atascos medidos llegan a ~30 s
FIND_PAGE_SIZE = 200  # el DVR devuelve como máximo 100 por llamada sin importar el "count"


class LightPriority:
    """Menor número = más urgente (mismo criterio que DownloadPriority)."""

    USER = 0  # alguien espera la respuesta ahora mismo (elegir un día, cambiar de mes)
    PERIODIC = 1  # refrescos y adelantos internos que nadie está esperando


class LightQueryCancelled(Exception):
    """El llamador canceló (stop_event) antes de que la consulta terminara."""


@dataclass(order=True)
class _QueueItem:
    priority: int
    seq: int
    job: "_Job | None" = field(compare=False)


@dataclass
class _Job:
    work: Callable[[], Any]
    stop_event: threading.Event
    future: Future


def parse_items(payload: str) -> list[dict[str, str]]:
    """Convierte las líneas `items[N].Campo=valor` de findNextFile en una
    lista de diccionarios, en el orden de N."""
    items: dict[int, dict[str, str]] = {}
    pattern = re.compile(r"items\[(\d+)\]\.([A-Za-z0-9_]+)=(.*)")
    for line in payload.splitlines():
        match = pattern.match(line.strip())
        if match:
            items.setdefault(int(match.group(1)), {})[match.group(2)] = match.group(3).strip()
    return [items[index] for index in sorted(items)]


def _http_get(url: str, auth: HTTPDigestAuth) -> str:
    response = requests.get(url, auth=auth, timeout=LIGHT_TIMEOUT)
    response.raise_for_status()
    return response.text


class LightQueryManager:
    """Cola de prioridad + LIGHT_THREADS hilos fijos para consultas CGI
    ligeras. Como RecordingDownloadManager, no sabe nada de Qt ni de un
    llamador concreto: cada pedido trae host y credenciales, y devuelve un
    Future (resultado, o excepción tras agotar los reintentos)."""

    def __init__(
        self,
        threads: int = LIGHT_THREADS,
        max_attempts: int = LIGHT_MAX_ATTEMPTS,
        retry_delay: float = LIGHT_RETRY_DELAY,
    ) -> None:
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._queue: PriorityQueue[_QueueItem] = PriorityQueue()
        self._seq_counter = itertools.count()
        self._workers = [
            threading.Thread(target=self._worker_loop, name=f"LightQuery-{i}", daemon=True) for i in range(threads)
        ]
        for worker in self._workers:
            worker.start()

    def submit_get(
        self,
        host: str,
        username: str,
        password: str,
        path: str,
        priority: int,
        stop_event: threading.Event,
    ) -> Future:
        """GET http://host/{path} (p. ej. "cgi-bin/magicBox.cgi?action=getSystemInfo");
        el Future se resuelve con el texto de la respuesta."""

        def work() -> str:
            return _http_get(f"http://{host}/{path.lstrip('/')}", HTTPDigestAuth(username, password))

        return self._submit(work, priority, stop_event)

    def submit_find_files(
        self,
        host: str,
        username: str,
        password: str,
        channel: int,
        start: datetime,
        end: datetime,
        max_pages: int,
        priority: int,
        stop_event: threading.Event,
    ) -> Future:
        """Búsqueda de grabaciones de un canal (mediaFileFind.cgi completo
        en un solo trabajo). Junta hasta `max_pages` páginas, parando antes
        si una viene vacía (única señal confiable de que ya no hay más: ver
        MAX_RECORDED_DAYS_PAGES en dvr_client.py). El Future se resuelve con
        la lista de diccionarios de cada archivo (StartTime, EndTime...)."""

        def work() -> list[dict[str, str]]:
            auth = HTTPDigestAuth(username, password)
            base = f"http://{host}/cgi-bin/mediaFileFind.cgi"
            match = re.search(r"result=(\d+)", _http_get(f"{base}?action=factory.create", auth))
            if not match:
                raise RuntimeError("No se pudo iniciar la sesión de búsqueda en el DVR.")
            object_id = match.group(1).strip()
            try:
                start_query = start.strftime("%Y-%m-%d%%20%H:%M:%S")
                end_query = end.strftime("%Y-%m-%d%%20%H:%M:%S")
                _http_get(
                    f"{base}?action=findFile&object={object_id}&condition.Channel={channel}"
                    f"&condition.StartTime={start_query}&condition.EndTime={end_query}",
                    auth,
                )
                found: list[dict[str, str]] = []
                for _ in range(max_pages):
                    items = parse_items(_http_get(f"{base}?action=findNextFile&object={object_id}&count={FIND_PAGE_SIZE}", auth))
                    if not items:
                        break
                    found.extend(items)
                return found
            finally:
                try:
                    _http_get(f"{base}?action=destroy&object={object_id}", auth)
                except Exception:
                    pass

        return self._submit(work, priority, stop_event)

    def shutdown(self) -> None:
        for _ in self._workers:
            self._queue.put(_QueueItem(priority=0, seq=next(self._seq_counter), job=None))
        for worker in self._workers:
            worker.join(timeout=5.0)

    def _submit(self, work: Callable[[], Any], priority: int, stop_event: threading.Event) -> Future:
        future: Future = Future()
        job = _Job(work=work, stop_event=stop_event, future=future)
        self._queue.put(_QueueItem(priority=priority, seq=next(self._seq_counter), job=job))
        return future

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item.job is None:
                return
            self._run_job(item.job)

    def _run_job(self, job: _Job) -> None:
        last_error: Exception | None = None
        for attempt in range(self._max_attempts):
            if job.stop_event.is_set():
                job.future.set_exception(LightQueryCancelled())
                return
            try:
                job.future.set_result(job.work())
                return
            except Exception as exc:  # cada intento cierra su propia conexión al fallar (requests)
                last_error = exc
            if attempt < self._max_attempts - 1 and job.stop_event.wait(self._retry_delay):
                job.future.set_exception(LightQueryCancelled())
                return
        job.future.set_exception(last_error or RuntimeError("consulta fallida"))
