from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

_CLIP_CACHE: dict[tuple[date, int], list[tuple[datetime, datetime]]] = {}


def clips_for(day: date, channel: int) -> list[tuple[datetime, datetime]]:
    """Horario de grabacion falso pero determinista: la misma fecha+canal
    siempre produce los mismos clips. Necesario porque el flujo real hace
    varias llamadas HTTP separadas en momentos distintos (findFile,
    findNextFile y, despues, loadfile.cgi al hacer clic en la linea de
    tiempo) que deben coincidir siempre en los mismos rangos."""
    key = (day, channel)
    if key not in _CLIP_CACHE:
        _CLIP_CACHE[key] = _generate_clips(day, channel)
    return _CLIP_CACHE[key]


def _generate_clips(day: date, channel: int) -> list[tuple[datetime, datetime]]:
    rnd = random.Random(f"{day.isoformat()}-ch{channel}")
    clips: list[tuple[datetime, datetime]] = []
    cursor = datetime.combine(day, time(7, 0))
    day_end = datetime.combine(day, time(22, 0))

    while cursor < day_end:
        duration = timedelta(minutes=rnd.randint(45, 90))
        end = min(cursor + duration, day_end)
        clips.append((cursor, end))
        # Huecos ocasionales para poder probar "sin grabacion en esa hora"
        # sin depender de un DVR real.
        gap = timedelta(minutes=rnd.choice([0, 0, 0, 10, 25]))
        cursor = end + gap

    return clips


def find_containing_clip(channel: int, start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
    for clip_start, clip_end in clips_for(start.date(), channel):
        if clip_start <= start and end <= clip_end:
            return clip_start, clip_end
    return None


def find_overlapping_clips(channel: int, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    return [
        (clip_start, clip_end)
        for clip_start, clip_end in clips_for(start.date(), channel)
        if clip_start < end and clip_end > start
    ]
