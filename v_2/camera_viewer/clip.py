from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Clip:
    channel: int
    start: datetime
    end: datetime
