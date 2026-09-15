from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

_CLIP_CACHE: dict[tuple[date, int], list[tuple[datetime, datetime]]] = {}

# Probabilidad (por dia+canal, determinista via la seed) de que ese dia no
# tenga NINGUNA grabacion -- para poder probar el opacado del calendario y
# los huecos del timeline sin depender de que el DVR real tenga un dia asi
# a la mano.
ZERO_RECORDING_DAY_CHANCE = 0.15

# Probabilidad de que un bloque de una hora particular, dentro de un dia
# que SI graba, falte -- hueco corto (p. ej. un reinicio de camara), no
# todo el dia. Se aplica independiente por hora, asi que casi siempre un
# dia grabado sale continuo, con un hueco ocasional.
INTRA_DAY_GAP_CHANCE = 0.04


def clips_for(day: date, channel: int) -> list[tuple[datetime, datetime]]:
    """Horario de grabacion falso pero determinista: la misma fecha+canal
    siempre produce los mismos clips (salvo el dia de HOY, ver mas abajo).
    Necesario porque el flujo real hace varias llamadas HTTP separadas en
    momentos distintos (findFile, findNextFile y, despues, loadfile.cgi al
    hacer clic en la linea de tiempo) que deben coincidir siempre en los
    mismos rangos."""
    key = (day, channel)
    if key not in _CLIP_CACHE:
        _CLIP_CACHE[key] = _generate_clips(day, channel)
    return _CLIP_CACHE[key]


def _generate_clips(day: date, channel: int) -> list[tuple[datetime, datetime]]:
    """Bloques de una hora en punto (00:00-01:00, 01:00-02:00, ...) cubriendo
    el dia completo -- asi es como graba el DVR real (verificado contra uno
    real: 19-20 archivos por dia y canal, cortados en la hora exacta). Si
    `day` es hoy, el ultimo bloque corta en el momento actual en vez de
    llegar a las 24:00, igual que el archivo que el DVR real todavia esta
    escribiendo cuando se le pregunta. Un dia futuro (mas alla de hoy)
    nunca tiene grabacion -- todavia no ha pasado."""
    now = datetime.now()
    if day > now.date():
        return []

    # La decision de "este dia no grabo nada" es POR DIA, no por canal --
    # comparte semilla entre los 4 canales a proposito, para simular algo
    # que los afecta a todos por igual (el DVR reiniciandose, sin luz),
    # igual que pasaria de verdad. Si fuera independiente por canal la
    # probabilidad de que los 4 coincidan en cero series casi nula
    # (0.15^4 ~= 0.05%), y el calendario/timeline nunca tendrian un dia
    # realista para probar el opacado por falta de grabacion.
    day_rnd = random.Random(f"{day.isoformat()}-allchannels")
    if day_rnd.random() < ZERO_RECORDING_DAY_CHANCE:
        return []

    # Los huecos DENTRO del dia si son independientes por canal (una camara
    # puede fallar sin que le pase lo mismo a las demas).
    rnd = random.Random(f"{day.isoformat()}-ch{channel}")

    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    if day == now.date():
        day_end = min(day_end, now)

    clips: list[tuple[datetime, datetime]] = []
    cursor = day_start
    while cursor < day_end:
        chunk_end = min(cursor + timedelta(hours=1), day_end)
        if rnd.random() >= INTRA_DAY_GAP_CHANCE:
            clips.append((cursor, chunk_end))
        cursor = chunk_end

    return clips


def find_containing_clip(channel: int, start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
    for clip_start, clip_end in clips_for(start.date(), channel):
        if clip_start <= start and end <= clip_end:
            return clip_start, clip_end
    return None


def find_overlapping_clips(channel: int, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """A diferencia de find_containing_clip (una sola grabacion puntual
    para reproducir), esto alimenta tanto la busqueda de un dia como la
    consulta de "dias con grabacion" de un mes completo -- el rango puede
    cruzar muchos dias, asi que hay que recorrer clips_for() para cada uno
    en vez de asumir que todo cae en start.date()."""
    results: list[tuple[datetime, datetime]] = []
    day = start.date()
    while day <= end.date():
        for clip_start, clip_end in clips_for(day, channel):
            if clip_start < end and clip_end > start:
                results.append((clip_start, clip_end))
        day += timedelta(days=1)
    return results
