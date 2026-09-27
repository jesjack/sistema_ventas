from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import archive_compactor, archive_index as idx, download_client
from .archive_compactor import QUALITY_MEDIUM, CompactionResult
from .clip import Clip, clips_from_items
from .download_manager import DownloadPriority
from .dvr_log import logger
from .export_clip import free_bytes_for, own_as_user, unique_path
from .export_hours import WAIT_POLL, merge_intervals
from .light_query_manager import LightPriority
from .dvr_credentials import dvr_credentials
from .shared_paths import (
    ARCHIVE_DIR,
    ARCHIVER_DISABLED_MARKER,
    SHARE_RUNTIME_DIR,
    apply_shared_umask,
    ensure_shared_root,
)

# Archivador pasivo: mientras la app de cámaras está cerrada (o abierta: no le estorba, ver
# DownloadPriority.ARCHIVE, la más baja de todas), va copiando a la PC lo más VIEJO que el DVR
# tenga -- lo primero que se sobrescribirá -- para que "ver más atrás de lo que guarda el DVR" sea
# posible. Idea del usuario (2026-09-23): en vez de duplicar lo reciente, el DVR sigue guardando
# sus últimos días y la PC guarda todo lo anterior; los dos rangos se SUMAN en vez de solaparse.
#
# Cómo decide qué bajar (sin Qt, ver la nota de export_hours.py): para cada canal, `dvr_oldest`
# es lo más viejo que el DVR todavía tiene (se vuelve a preguntar cada OLDEST_REFRESH_SECONDS,
# nunca se asume un "tiempo de retención" fijo -- varía con cuánto se grabó). Nunca se archiva
# más allá de `dvr_oldest + margin_days`: ese margen es el colchón para que la PC pueda estar
# apagada `margin_days` seguidos (fin de semana) sin perder nada -- lo que el DVR aún conserva no
# hace falta duplicarlo. Un "cursor" por canal (en el índice, no en memoria) recuerda hasta dónde
# ya se revisó, avance haya habido grabación o no (un hueco real -- cámara apagada un rato -- se
# salta sin quedarse atascado ahí para siempre).
#
# Aterriza el .dav tal cual (rápido, sin usar CPU/GPU) y por separado, más despacio, lo compacta
# (archive_compactor.py): recomprimido, un segmento crudo pesa una fracción -- 3 a 30 veces menos,
# medido en el DVR real el 2026-09-21/23, según cuánto se mueve la escena.

DEFAULT_CHANNELS = (1, 2, 3, 4)

DEFAULT_MARGIN_DAYS = 3.0  # el negocio cierra sábado y domingo: hasta ~2.5 días seguidos apagada
DEFAULT_SEGMENT_SECONDS = 300.0  # 5 min por trozo aterrizado
DEFAULT_MAX_BYTES = 500 * 1024**3
DEFAULT_MIN_FREE_BYTES = 150 * 1024**3
DEFAULT_CAP_MBPS = 30.0  # tope propio del archivador -- defensivo: la prioridad ARCHIVE (la más
#                          baja) y un solo trozo en vuelo ya lo dejan sin competir con nada más

OLDEST_PROBE_DAYS = 30  # ventana para preguntarle al DVR "¿qué es lo más viejo que tienes?"
OLDEST_PROBE_MAX_PAGES = 50  # igual que MAX_RECORDED_DAYS_PAGES en dvr_client.py -- de sobra para 30 días
LOOKUP_WINDOW_SECONDS = 86400.0  # cuánto se pide de una vez al buscar grabaciones (1 día: cachea varios trozos)
LOOKUP_MAX_PAGES = 10
OLDEST_REFRESH_SECONDS = 1800.0
CYCLE_IDLE_SLEEP = 30.0  # nada que hacer en ningún canal ahora mismo: antes de volver a mirar
CHUNK_RETRIES = 2
CHUNK_RETRY_DELAYS = (2.0, 5.0)
MIN_PIECE_SECONDS = 1.0

# El DVR real (2026-09-25) estuvo caído >90 min y el archivador siguió golpeándolo sin pausa: cada
# trozo fallido pasaba a intentar el siguiente de inmediato, sin ninguna espera creciente. Con
# esto, tras DVR_BACKOFF_FAILURE_THRESHOLD fallos SEGUIDOS (de cualquier canal: query o descarga)
# se asume que el DVR entero está caído/reiniciando, no que un trozo tuvo mala suerte, y las
# esperas entre ciclos se van doblando hasta un tope -- el primer intento que sí responda (p. ej.
# apenas el DVR termina de reiniciarse) reinicia el conteo y el ritmo normal, sin intervención
# manual.
DVR_BACKOFF_FAILURE_THRESHOLD = 2
DVR_BACKOFF_INITIAL = CYCLE_IDLE_SLEEP
DVR_BACKOFF_MAX = 300.0
DVR_BACKOFF_MULTIPLIER = 2.0
COMPACT_ATTEMPT_LIMIT = 20  # por ciclo: un segmento roto no debe bloquear a los demás para siempre


def eligible_ceiling(dvr_oldest: datetime, margin_days: float, now: datetime) -> datetime:
    """Nunca más allá de esto: lo que el DVR aún conservará por al menos `margin_days` más no
    hace falta archivarlo (nunca se está más adelantado que el propio reloj)."""
    return min(now, dvr_oldest + timedelta(days=margin_days))


def next_window(checked_until: datetime | None, dvr_oldest: datetime, ceiling: datetime) -> tuple[datetime, datetime] | None:
    """Desde dónde seguir revisando y hasta dónde, o None si ya no hay nada por delante (se
    alcanzó `ceiling`). Si `checked_until` quedó por detrás de `dvr_oldest` (la PC estuvo apagada
    más de lo que el margen cubría), se salta a `dvr_oldest`: lo de en medio ya no está ni en el
    DVR ni se puede recuperar."""
    start = max(checked_until, dvr_oldest) if checked_until is not None else dvr_oldest
    if start >= ceiling:
        return None
    return start, ceiling


def chunk_recorded(
    clips: list[Clip], window_start: datetime, window_end: datetime, segment_seconds: float
) -> list[tuple[datetime, datetime]]:
    """Los trozos de a lo más `segment_seconds` a bajar dentro de [window_start, window_end),
    solo donde de verdad hay grabación -- a diferencia de exportar horas, aquí un hueco no
    produce nada (no hay "tramo negro": esto solo copia lo que existe, no arma un video para
    ver de corrido)."""
    pieces: list[tuple[datetime, datetime]] = []
    chunk = timedelta(seconds=segment_seconds)
    for start, end in merge_intervals(clips):
        start, end = max(start, window_start), min(end, window_end)
        if (end - start).total_seconds() < MIN_PIECE_SECONDS:
            continue
        moment = start
        while moment < end:
            following = min(moment + chunk, end)
            if (end - following).total_seconds() < MIN_PIECE_SECONDS:  # resto minúsculo: se pega al trozo
                following = end
            pieces.append((moment, following))
            moment = following
    return pieces


@dataclass
class ArchiverConfig:
    channels: tuple[int, ...] = DEFAULT_CHANNELS
    host: str = ""
    username: str = ""
    password: str = ""
    archive_dir: Path = field(default_factory=lambda: ARCHIVE_DIR)
    margin_days: float = DEFAULT_MARGIN_DAYS
    segment_seconds: float = DEFAULT_SEGMENT_SECONDS
    max_bytes: int = DEFAULT_MAX_BYTES
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES
    cap_mbps: float | None = DEFAULT_CAP_MBPS
    quality: int = QUALITY_MEDIUM


class Archiver:
    """El archivador: `run_once()` hace UNA unidad de trabajo (bajar un trozo o compactar uno
    pendiente) y devuelve si hizo algo; `run_forever()` lo repite con una pausa cuando no hay
    nada que hacer. Todo lo que habla con el DVR o con ffmpeg entra por parámetro (`submit`,
    `find_files`, `compact`...), así se prueba entero sin red ni GPU."""

    def __init__(
        self,
        config: ArchiverConfig,
        submit: Callable[..., Future] | None = None,
        find_files: Callable[..., Future] | None = None,
        compact: Callable[..., CompactionResult] | None = None,
        free_bytes: Callable[[Path], int] | None = None,
        conn=None,
        clock: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._submit = submit or download_client.submit
        self._find_files = find_files or download_client.find_files
        self._compact = compact or archive_compactor.compact
        self._free_bytes = free_bytes or free_bytes_for
        self._now = clock
        self._monotonic = monotonic
        self.stop = threading.Event()
        self._oldest_cache: dict[int, tuple[float, datetime]] = {}
        self._pending: dict[int, list[tuple[datetime, datetime]]] = {}
        self._channel_index = 0
        self._consecutive_failures = 0
        self._backoff = DVR_BACKOFF_INITIAL
        # No solo por si esta clase se usa fuera de `if __name__ == "__main__"` de este módulo
        # (p. ej. desde un script suelto, o más adelante desde la propia app): que la carpeta
        # del archivo quede lista para cualquier usuario del grupo no puede depender de que quien
        # instancie Archiver se acuerde de llamarlo antes.
        apply_shared_umask()
        ensure_shared_root(config.archive_dir)
        self.conn = conn or idx.open_db(config.archive_dir / "index.sqlite3")

    def close(self) -> None:
        self.conn.close()

    # -- bucle principal ---------------------------------------------------------------------------

    def run_once(self) -> bool:
        """Una unidad de trabajo: primero intenta avanzar el aterrizado (más urgente: es lo que
        protege contra perder grabación), y si no hubo nada que hacer, intenta compactar un
        segmento pendiente. True si hizo algo de cualquiera de los dos."""
        return self._land_one_piece() or self._compact_one_pending()

    def run_forever(self) -> None:
        while not self.stop.is_set():
            try:
                did_something = self.run_once()
            except Exception:
                logger.exception("archiver: fallo inesperado en un ciclo, se sigue")
                did_something = False
            if self._consecutive_failures >= DVR_BACKOFF_FAILURE_THRESHOLD:
                wait = self._backoff
                self._backoff = min(self._backoff * DVR_BACKOFF_MULTIPLIER, DVR_BACKOFF_MAX)
                logger.warning(
                    "archiver: %d fallos seguidos con el DVR, se espera %.0fs antes de reintentar "
                    "(¿está caído o reiniciando?)", self._consecutive_failures, wait,
                )
                self.stop.wait(wait)
            elif not did_something:
                self.stop.wait(CYCLE_IDLE_SLEEP)

    def _register_failure(self) -> None:
        self._consecutive_failures += 1

    def _register_success(self) -> None:
        if self._consecutive_failures >= DVR_BACKOFF_FAILURE_THRESHOLD:
            logger.info("archiver: el DVR volvió a responder tras %d fallos seguidos, ritmo normal", self._consecutive_failures)
        self._consecutive_failures = 0
        self._backoff = DVR_BACKOFF_INITIAL

    def request_stop(self) -> None:
        self.stop.set()

    # -- aterrizar ------------------------------------------------------------------------------------

    def _land_one_piece(self) -> bool:
        channels = self.config.channels
        if not channels:
            return False
        for _ in range(len(channels)):  # una vuelta completa: si nadie tiene nada que hacer, listo
            channel = channels[self._channel_index]
            self._channel_index = (self._channel_index + 1) % len(channels)
            if self._archive_one_piece(channel):
                return True
        return False

    def _archive_one_piece(self, channel: int) -> bool:
        now = self._now()
        dvr_oldest = self._dvr_oldest(channel, now)
        if dvr_oldest is None:
            self._register_failure()
            return False  # el DVR no respondió o no tiene nada de este canal
        ceiling = eligible_ceiling(dvr_oldest, self.config.margin_days, now)
        checked_until = idx.get_cursor(self.conn, channel)
        window = next_window(checked_until, dvr_oldest, ceiling)
        if window is None:
            self._pending.pop(channel, None)
            return False

        pending = self._pending.get(channel)
        if not pending:
            lookup_end = min(window[1], window[0] + timedelta(seconds=LOOKUP_WINDOW_SECONDS))
            clips = self._fetch_clips(channel, window[0], lookup_end, LOOKUP_MAX_PAGES)
            if clips is None:
                self._register_failure()
                return False  # la consulta falló: NO se avanza el cursor, se reintenta en el próximo ciclo
            pending = chunk_recorded(clips, window[0], lookup_end, self.config.segment_seconds)
            if not pending:
                idx.set_cursor(self.conn, channel, lookup_end)  # de verdad no hay nada grabado ahí
                self._register_success()
                return True
            self._pending[channel] = pending

        # No se saca de `pending` (pop) hasta que aterriza bien: si el DVR está caído, el mismo
        # trozo se reintenta en el siguiente ciclo en vez de perderse (antes el cursor avanzaba
        # igual aunque _land_piece fallara, saltándose para siempre lo que no se pudo bajar).
        piece_start, piece_end = pending[0]
        if not self._land_piece(channel, piece_start, piece_end, now):
            self._register_failure()
            return False
        pending.pop(0)
        if not pending:
            del self._pending[channel]
        idx.set_cursor(self.conn, channel, piece_end)
        self._enforce_budget()
        self._register_success()
        return True

    def _land_piece(self, channel: int, start: datetime, end: datetime, now: datetime) -> bool:
        source, elapsed = self._fetch_with_retries(channel, start, end)
        if source is None:
            return False
        channel_dir = self.config.archive_dir / f"ch{channel}"
        channel_dir.mkdir(parents=True, exist_ok=True)
        final = unique_path(channel_dir, f"{start:%Y-%m-%d_%H%M%S}_a_{end:%H%M%S}.dav")
        partial = final.with_name(f".{final.stem}.part{final.suffix}")
        try:
            shutil.move(str(source), str(partial))
            self._apply_rate_cap(partial.stat().st_size, elapsed)
            partial.replace(final)
            own_as_user(final)
        except OSError as exc:
            logger.warning("archiver: no se pudo guardar el trozo ch%d %s-%s: %s", channel, start, end, exc)
            partial.unlink(missing_ok=True)
            return False
        finally:
            source.unlink(missing_ok=True)
        relative = str(final.relative_to(self.config.archive_dir))
        idx.add_segment(self.conn, channel, start, end, relative, final.stat().st_size, now=now)
        return True

    def _fetch_with_retries(self, channel: int, start: datetime, end: datetime) -> tuple[Path | None, float]:
        for attempt in range(1 + CHUNK_RETRIES):
            if self.stop.is_set():
                return None, 0.0
            began = self._monotonic()
            future = self._submit(
                self.config.host, self.config.username, self.config.password, channel, start, end,
                DownloadPriority.ARCHIVE, self.stop,
            )
            source = self._wait_download(future)
            elapsed = self._monotonic() - began
            if source is not None:
                return source, elapsed
            if attempt < CHUNK_RETRIES and self.stop.wait(CHUNK_RETRY_DELAYS[min(attempt, len(CHUNK_RETRY_DELAYS) - 1)]):
                return None, 0.0
        logger.warning("archiver: no se pudo bajar ch%d %s-%s tras %d intentos", channel, start, end, 1 + CHUNK_RETRIES)
        return None, 0.0

    def _wait_download(self, future: Future) -> Path | None:
        while True:
            try:
                return future.result(timeout=WAIT_POLL)
            except FutureTimeout:
                if self.stop.is_set():
                    return None
            except Exception:
                return None

    def _apply_rate_cap(self, size_bytes: int, elapsed: float) -> None:
        if not self.config.cap_mbps:
            return
        cap_bytes_per_second = self.config.cap_mbps * 1e6 / 8
        minimum_seconds = size_bytes / cap_bytes_per_second
        if elapsed < minimum_seconds:
            self.stop.wait(minimum_seconds - elapsed)  # `wait`, no `sleep`: una cancelación no se queda esperando

    # -- lo más viejo que el DVR conserva -------------------------------------------------------------

    def _dvr_oldest(self, channel: int, now: datetime) -> datetime | None:
        cached = self._oldest_cache.get(channel)
        if cached is not None and self._monotonic() - cached[0] < OLDEST_REFRESH_SECONDS:
            return cached[1]
        clips = self._fetch_clips(channel, now - timedelta(days=OLDEST_PROBE_DAYS), now, OLDEST_PROBE_MAX_PAGES)
        if not clips:  # consulta fallida o el canal no tiene nada: se sigue con lo último que se supo
            return cached[1] if cached is not None else None
        oldest = min(clip.start for clip in clips)
        self._oldest_cache[channel] = (self._monotonic(), oldest)
        return oldest

    def _fetch_clips(self, channel: int, start: datetime, end: datetime, max_pages: int) -> list[Clip] | None:
        """None = la consulta falló (nada que aprender de eso todavía); lista vacía = se
        consultó bien y de verdad no hay nada grabado en ese tramo."""
        future = self._find_files(
            self.config.host, self.config.username, self.config.password, channel, start, end,
            max_pages, LightPriority.PERIODIC, threading.Event(),
        )
        while True:
            try:
                items = future.result(timeout=WAIT_POLL)
                return clips_from_items(channel, items)
            except FutureTimeout:
                if self.stop.is_set():
                    return None
            except Exception:
                return None  # ya quedó en el log del propio carril de consultas (ver light_query_manager)

    # -- presupuesto de disco ---------------------------------------------------------------------------

    def _enforce_budget(self) -> None:
        while idx.total_bytes(self.conn) > self.config.max_bytes or self._free_bytes(self.config.archive_dir) < self.config.min_free_bytes:
            segment = idx.oldest_segment(self.conn)
            if segment is None:
                return  # no queda nada que desalojar
            (self.config.archive_dir / segment.path).unlink(missing_ok=True)
            idx.delete_segment(self.conn, segment.id)

    # -- compactar --------------------------------------------------------------------------------------

    def _compact_one_pending(self) -> bool:
        """Prueba con los pendientes más viejos, uno por uno, hasta lograr compactar alguno (o
        agotar el límite): un segmento roto no debe bloquear la compactación de todos los demás
        para siempre. Devuelve False solo si NINGUNO de los intentados se pudo compactar."""
        for segment in idx.pending_compaction(self.conn, limit=COMPACT_ATTEMPT_LIMIT):
            source = self.config.archive_dir / segment.path
            if not source.exists():
                idx.delete_segment(self.conn, segment.id)  # el índice y el disco se desincronizaron
                return True
            destination = source.with_suffix(".mp4")
            try:
                result = self._compact(source, destination, segment.seconds, self.config.quality, stop=self.stop)
            except Exception as exc:
                logger.warning("archiver: no se pudo compactar %s: %s (se deja crudo, se intenta el siguiente)", source, exc)
                continue
            idx.mark_compacted(self.conn, segment.id, str(destination.relative_to(self.config.archive_dir)), result.bytes)
            source.unlink(missing_ok=True)
            return True
        return False


if __name__ == "__main__":
    import signal

    from . import dvr_log
    from .singleton_lock import acquire_singleton_lock

    apply_shared_umask()
    ensure_shared_root(SHARE_RUNTIME_DIR)
    if ARCHIVER_DISABLED_MARKER.exists():
        print(f"archiver: desactivado a mano ({ARCHIVER_DISABLED_MARKER} existe); no arranca. Bórralo para reactivarlo.")
    elif (lock_file := acquire_singleton_lock(SHARE_RUNTIME_DIR / "archiver.lock")) is None:
        print("archiver ya está corriendo; no se abre otra instancia.")
    else:
        dvr_log.enable()
        host, username, password = dvr_credentials()
        archiver_config = ArchiverConfig(host=host, username=username, password=password)
        print(f"archiver: guardando en {archiver_config.archive_dir}")
        main_engine = Archiver(archiver_config)
        # El POS lo lanza y lo cierra con él (nucleo/arranque.py): un SIGTERM debe pedir que
        # pare pronto, no matarlo a medio escribir un trozo. Solo desde el hilo principal (única
        # restricción real de signal.signal), que es justo donde estamos parados aquí.
        signal.signal(signal.SIGTERM, lambda signum, frame: main_engine.request_stop())
        main_engine.run_forever()
