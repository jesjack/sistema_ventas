from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Almacén local de bloques de video ya descargados (uno por rango de tiempo y
# canal). Es lo que hace instantáneos los saltos de ±10 s y el volver atrás:
# la reproducción consulta aquí ANTES de pedir nada al DVR, y los bloques
# vecinos se descargan por adelantado (ver channel_player.py). Los archivos se
# leen tal cual los entrega el DVR (contenedor "dhav", H.264, sin cifrar): con
# OpenCV se salta por número de cuadro con precisión exacta y en ~50 ms, y
# reempaquetarlos a MP4/MKV no mejora nada (informes/REPRODUCCION_VELOCIDAD.md).
# Vive en disco (el sistema los mantiene en su caché de memoria).


@dataclass(frozen=True)
class ChunkEntry:
    channel: int
    start: datetime
    end: datetime
    path: Path


class ChunkStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, list[ChunkEntry]] = {}

    def add(self, channel: int, start: datetime, end: datetime, path: Path) -> ChunkEntry:
        """Registra un bloque. Si ya había uno con el mismo rango se queda el
        existente y se borra el archivo repetido."""
        with self._lock:
            entries = self._entries.setdefault(channel, [])
            for existing in entries:
                if existing.start == start and existing.end == end:
                    if existing.path != path:
                        path.unlink(missing_ok=True)
                    return existing
            entry = ChunkEntry(channel, start, end, path)
            entries.append(entry)
            return entry

    def find(self, channel: int, moment: datetime) -> ChunkEntry | None:
        """El bloque que contiene `moment` (el que llegue más lejos si hay varios)."""
        with self._lock:
            best: ChunkEntry | None = None
            for entry in self._entries.get(channel, ()):
                if entry.start <= moment < entry.end and (best is None or entry.end > best.end):
                    best = entry
            return best

    def remove(self, entry: ChunkEntry) -> None:
        """Quita un bloque (p. ej. archivo dañado) y borra su archivo."""
        with self._lock:
            entries = self._entries.get(entry.channel, [])
            if entry in entries:
                entries.remove(entry)
        entry.path.unlink(missing_ok=True)

    def entries(self, channel: int) -> list[ChunkEntry]:
        with self._lock:
            return sorted(self._entries.get(channel, ()), key=lambda entry: entry.start)

    def prune(self, channel: int, keep_from: datetime, keep_to: datetime) -> None:
        """Borra los bloques que quedan enteros fuera de [keep_from, keep_to].
        Borrar un archivo que un canal tiene abierto es seguro en Linux: el
        canal sigue leyéndolo hasta cerrarlo."""
        with self._lock:
            keep, drop = [], []
            for entry in self._entries.get(channel, ()):
                (drop if entry.end <= keep_from or entry.start >= keep_to else keep).append(entry)
            self._entries[channel] = keep
        for entry in drop:
            entry.path.unlink(missing_ok=True)

    def clear(self) -> None:
        with self._lock:
            dropped = [entry for entries in self._entries.values() for entry in entries]
            self._entries = {}
        for entry in dropped:
            entry.path.unlink(missing_ok=True)
