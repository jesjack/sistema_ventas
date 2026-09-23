from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Clip:
    channel: int
    start: datetime
    end: datetime


def clips_from_items(channel: int, items: list[dict[str, str]]) -> list[Clip]:
    """Convierte lo que devuelve mediaFileFind (ver light_query_manager.submit_find_files) en
    Clip. Sin Qt a propósito: la usa DVRClient (dvr_client.py) y también archiver.py, que corre
    como proceso aparte sin ventana."""
    clips: list[Clip] = []
    for item in items:
        start, end = item.get("StartTime"), item.get("EndTime")
        if start and end:
            clips.append(
                Clip(
                    channel=channel,
                    start=datetime.strptime(start.strip(), "%Y-%m-%d %H:%M:%S"),
                    end=datetime.strptime(end.strip(), "%Y-%m-%d %H:%M:%S"),
                )
            )
    return clips
