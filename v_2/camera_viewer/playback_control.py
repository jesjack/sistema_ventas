from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

# Estado de reproducción COMPARTIDO por los 4 canales: pausa, velocidad, sentido
# (normal/reversa) y, sobre todo, el RELOJ DE REFERENCIA. Cada canal tiene su
# propio hilo, pero todos muestran el cuadro cuya hora de video coincide con la
# hora de este reloj -- así no se desfasan aunque uno arranque tarde, se atrase
# esperando una descarga o la interfaz tarde en pintarlo. No usa Qt: los hilos lo
# consultan en cada cuadro, y la interfaz lo cambia desde su hilo.
#
# Arranque conjunto ("barrera"): tras reset() o request_seek() el reloj queda
# detenido en la hora pedida y arranca cuando los canales avisan que tienen su
# primer cuadro listo (announce_ready) o que no tienen nada que mostrar
# (announce_absent), o cuando pasan BARRIER_TIMEOUT segundos: el canal que
# tarda más no frena a los demás, se les une después saltando a la hora actual.

PAUSED_STATUS = "Pausa"
REVERSE_STATUS_PREFIX = "Reversa"
SYNC_STATUS = "Sincronizando..."
GATE_POLL = 0.1  # cada cuánto un hilo en pausa revisa si lo cancelaron
BARRIER_TIMEOUT = 6.0  # arranque: todos los canales tienen que descargar su primer bloque
SEEK_BARRIER_TIMEOUT = 2.0  # tras un salto: casi siempre está todo en disco; si uno debe descargar, no frena a los demás


class PlaybackControl:
    def __init__(self, channels: tuple[int, ...]) -> None:
        self._channels = channels
        self._cond = threading.Condition()
        self._paused = False
        self._speed = 1.0
        self._reverse = False
        # Sube cada vez que cambia el ritmo (reanudar, cambiar velocidad).
        self._epoch = 0
        self._steps = {channel: 0 for channel in channels}
        self._playing: set[int] = set()
        # Salto pendiente por canal (hora a la que ir). Gana el último pedido.
        self._seeks: dict[int, datetime] = {}
        # Reloj de referencia: en el instante `_wall` (time.monotonic) la hora de
        # video es `_media`; corre a `_speed` veces, hacia atrás si `_reverse`.
        self._media: datetime | None = None
        self._wall = 0.0
        self._running = False
        self._ready: set[int] = set()
        self._absent: set[int] = set()
        self._deadline = 0.0

    # -- estado simple -------------------------------------------------------------

    @property
    def paused(self) -> bool:
        with self._cond:
            return self._paused

    @property
    def speed(self) -> float:
        with self._cond:
            return self._speed

    @property
    def epoch(self) -> int:
        with self._cond:
            return self._epoch

    @property
    def reverse(self) -> bool:
        with self._cond:
            return self._reverse

    def status_text(self) -> str:
        with self._cond:
            if self._paused:
                return PAUSED_STATUS
            return f"{REVERSE_STATUS_PREFIX} x{self._speed:g}" if self._reverse else f"x{self._speed:g}"

    # -- reloj de referencia ----------------------------------------------------------------

    def has_clock(self) -> bool:
        with self._cond:
            return self._media is not None

    def clock_running(self) -> bool:
        with self._cond:
            return self._running

    def media_now(self) -> datetime | None:
        """Hora de video que marca el reloj ahora (None si no hay reproducción)."""
        with self._cond:
            return self._media_at(time.monotonic())

    def wall_for(self, media: datetime) -> float:
        """Instante (time.monotonic) en que el reloj marcará `media`. Solo tiene
        sentido con el reloj corriendo (ver clock_running)."""
        with self._cond:
            direction = -1.0 if self._reverse else 1.0
            return self._wall + (media - self._media).total_seconds() / (direction * self._speed)

    def _media_at(self, now: float) -> datetime | None:
        if self._media is None or not self._running:
            return self._media
        direction = -1.0 if self._reverse else 1.0
        return self._media + timedelta(seconds=direction * self._speed * (now - self._wall))

    def _rebase(self, now: float) -> None:
        """Fija la hora actual como punto de partida (antes de cambiar velocidad/sentido)."""
        if self._running and self._media is not None:
            self._media = self._media_at(now)
            self._wall = now

    def _arm(self, target: datetime, now: float, timeout: float) -> None:
        self._media = target
        self._running = False
        self._ready.clear()
        self._absent.clear()
        self._deadline = now + timeout

    def _start_if_ready(self, now: float) -> None:
        if self._running or self._paused or self._media is None:
            return
        if (self._ready | self._absent) >= set(self._channels) or now >= self._deadline:
            self._running = True
            self._wall = now
            self._cond.notify_all()

    def announce_ready(self, channel: int) -> None:
        """El canal tiene su primer cuadro listo para mostrar (barrera de arranque)."""
        with self._cond:
            self._ready.add(channel)
            self._absent.discard(channel)
            self._start_if_ready(time.monotonic())

    def announce_absent(self, channel: int) -> None:
        """El canal no tiene nada que mostrar (sin grabación, fin de segmento): no hace esperar a los demás."""
        with self._cond:
            self._absent.add(channel)
            self._ready.discard(channel)
            self._start_if_ready(time.monotonic())

    # -- control -----------------------------------------------------------------------------

    def reset(self, paused: bool, target: datetime | None = None) -> None:
        """Al arrancar una reproducción nueva (play_from). La velocidad y el sentido
        se conservan. `target` es la hora de video pedida (arma la barrera de
        arranque). Si arranca en pausa, cada canal deja pasar UN cuadro para que se
        vea la imagen del punto elegido."""
        with self._cond:
            self._paused = paused
            self._steps = {channel: (1 if paused else 0) for channel in self._channels}
            self._playing.clear()
            self._seeks.clear()
            self._epoch += 1
            if target is None:
                self._media, self._running = None, False
            else:
                self._arm(target, time.monotonic(), BARRIER_TIMEOUT)
            self._cond.notify_all()

    def set_paused(self, paused: bool) -> None:
        with self._cond:
            if paused == self._paused:
                return
            now = time.monotonic()
            if paused:
                self._rebase(now)
                self._running = False  # la hora de video queda congelada donde iba
            else:
                self._steps = {channel: 0 for channel in self._channels}
                self._epoch += 1
                if self._media is not None:
                    self._running = True
                    self._wall = now
            self._paused = paused
            self._cond.notify_all()

    def toggle_pause(self) -> bool:
        with self._cond:
            paused = not self._paused
        self.set_paused(paused)
        return paused

    def set_speed(self, speed: float) -> None:
        with self._cond:
            if speed == self._speed:
                return
            self._rebase(time.monotonic())
            self._speed = speed
            self._epoch += 1
            self._cond.notify_all()

    def set_reverse(self, reverse: bool) -> None:
        """Cambia el sentido (normal/reversa). La velocidad y la pausa se conservan."""
        with self._cond:
            if reverse == self._reverse:
                return
            self._rebase(time.monotonic())
            self._reverse = reverse
            self._epoch += 1
            self._cond.notify_all()

    # -- saltos (ver channel_player.py) ---------------------------------------

    def request_seek(self, target: datetime) -> None:
        """Pide a los 4 canales ir a `target` (y arma de nuevo la barrera de arranque
        para que vuelvan a salir juntos). En pausa, cada uno deja pasar un cuadro para
        mostrar la imagen del punto nuevo y sigue en pausa."""
        with self._cond:
            self._arm(target, time.monotonic(), SEEK_BARRIER_TIMEOUT)
            for channel in self._channels:
                self._seeks[channel] = target
                if self._paused:
                    self._steps[channel] += 1
            self._cond.notify_all()

    def take_seek(self, channel: int) -> datetime | None:
        with self._cond:
            return self._seeks.pop(channel, None)

    def peek_seek(self, channel: int) -> datetime | None:
        with self._cond:
            return self._seeks.get(channel)

    def wait_seek(self, channel: int, should_stop: Callable[[], bool]) -> datetime | None:
        """Espera (canal sin video que mostrar: fin de segmento, sin grabación)
        a que llegue un salto. None = lo cancelaron."""
        with self._cond:
            while channel not in self._seeks:
                if should_stop():
                    return None
                self._cond.wait(GATE_POLL)
            return self._seeks.pop(channel)

    def wait_turn(self, channel: int, should_stop: Callable[[], bool]) -> str:
        """Lo llama el hilo de un canal antes de cada cuadro. Devuelve "go"
        (seguir con el reloj), "step" (un cuadro suelto en pausa, sin esperar el
        reloj), "seek" (hay un salto pendiente para este canal: hay que atenderlo
        ANTES de esperar, porque atenderlo es lo que avisa que está listo para la
        barrera) o "stop" (lo cancelaron mientras esperaba). En pausa espera un
        permiso de cuadro; en marcha espera a que el reloj arranque (barrera)."""
        with self._cond:
            while True:
                if should_stop():
                    return "stop"
                if channel in self._seeks:
                    return "seek"
                if self._paused:
                    if self._steps.get(channel, 0) > 0:
                        self._steps[channel] -= 1
                        return "step"
                else:
                    self._start_if_ready(time.monotonic())
                    if self._running or self._media is None:
                        return "go"
                self._cond.wait(GATE_POLL)

    # -- qué canales están mostrando video (para no pisar "Descargando…") ----

    def mark_playing(self, channel: int, playing: bool) -> None:
        with self._cond:
            (self._playing.add if playing else self._playing.discard)(channel)

    def playing_channels(self) -> set[int]:
        with self._cond:
            return set(self._playing)
