from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

# Estado de reproducción COMPARTIDO por los 4 canales (pausa, velocidad y
# sentido normal/reversa). Cada canal tiene su propio hilo y su propio reloj
# (ver ChannelPlayer._play_entry); este objeto es lo único que tienen en común.
# No usa Qt: los hilos lo consultan en cada cuadro, y la interfaz lo cambia
# desde su hilo.

PAUSED_STATUS = "Pausa"
REVERSE_STATUS_PREFIX = "Reversa"
GATE_POLL = 0.1  # cada cuánto un hilo en pausa revisa si lo cancelaron


class PlaybackControl:
    def __init__(self, channels: tuple[int, ...]) -> None:
        self._channels = channels
        self._cond = threading.Condition()
        self._paused = False
        self._speed = 1.0
        self._reverse = False
        # Sube cada vez que cambia el ritmo (reanudar, cambiar velocidad): los
        # hilos lo comparan con el último que vieron y reinician su reloj de
        # cuadros, para no "ponerse al día" a golpes tras una pausa.
        self._epoch = 0
        self._steps = {channel: 0 for channel in channels}
        self._playing: set[int] = set()
        # Salto pendiente por canal (hora a la que ir). Gana el último pedido.
        self._seeks: dict[int, datetime] = {}

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

    def reset(self, paused: bool) -> None:
        """Al arrancar una reproducción nueva (play_from). La velocidad se
        y el sentido se conservan. Si arranca en pausa, cada canal deja pasar UN
        cuadro para que se vea la imagen del punto elegido."""
        with self._cond:
            self._paused = paused
            self._steps = {channel: (1 if paused else 0) for channel in self._channels}
            self._playing.clear()
            self._seeks.clear()
            self._epoch += 1
            self._cond.notify_all()

    def set_paused(self, paused: bool) -> None:
        with self._cond:
            if paused == self._paused:
                return
            self._paused = paused
            if not paused:
                self._steps = {channel: 0 for channel in self._channels}
                self._epoch += 1
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
            self._speed = speed
            self._epoch += 1
            self._cond.notify_all()

    def set_reverse(self, reverse: bool) -> None:
        """Cambia el sentido (normal/reversa). La velocidad y la pausa se conservan."""
        with self._cond:
            if reverse == self._reverse:
                return
            self._reverse = reverse
            self._epoch += 1
            self._cond.notify_all()

    # -- saltos (ver channel_player.py) ---------------------------------------

    def request_seek(self, target: datetime) -> None:
        """Pide a los 4 canales ir a `target`. En pausa, cada uno deja pasar un
        cuadro para mostrar la imagen del punto nuevo y sigue en pausa."""
        with self._cond:
            for channel in self._channels:
                self._seeks[channel] = target
                if self._paused:
                    self._steps[channel] += 1
            self._cond.notify_all()

    def give_step(self, channel: int) -> None:
        """Devuelve un permiso de cuadro no usado (el canal iba a mostrar un
        cuadro en pausa pero antes tuvo que ir a otro bloque a buscarlo)."""
        with self._cond:
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
        (seguir a ritmo normal), "step" (un cuadro suelto, sin esperar el
        ritmo) o "stop" (lo cancelaron mientras esperaba)."""
        with self._cond:
            while self._paused and self._steps.get(channel, 0) == 0:
                if should_stop():
                    return "stop"
                self._cond.wait(GATE_POLL)
            if should_stop():
                return "stop"
            if self._paused:
                self._steps[channel] -= 1
                return "step"
            return "go"

    # -- qué canales están mostrando video (para no pisar "Descargando…") ----

    def mark_playing(self, channel: int, playing: bool) -> None:
        with self._cond:
            (self._playing.add if playing else self._playing.discard)(channel)

    def playing_channels(self) -> set[int]:
        with self._cond:
            return set(self._playing)
