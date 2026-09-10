from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np

from .config import CHANNEL_COLORS_BGR

FRAME_SIZE = (640, 360)  # (ancho, alto)


def render_frame(channel: int, sim_time: datetime, caption: str) -> np.ndarray:
    """Genera un frame sintetico (no es video real de ninguna camara) para
    poder verificar a simple vista que el canal y la hora mostrados
    coinciden con lo que se pidio -- util para confirmar que el scrubbing
    de la linea de tiempo apunta al momento correcto."""
    width, height = FRAME_SIZE
    color = CHANNEL_COLORS_BGR.get(channel, (100, 100, 100))

    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = tuple(component // 4 for component in color)
    cv2.rectangle(frame, (0, 0), (width - 1, height - 1), color, 6)

    cv2.putText(frame, f"CANAL {channel} (EMULADO)", (24, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
    cv2.putText(frame, sim_time.strftime("%Y-%m-%d %H:%M:%S"), (24, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
    cv2.putText(frame, caption, (24, height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

    return frame


def encode_jpeg(frame: np.ndarray) -> bytes | None:
    ok, encoded = cv2.imencode(".jpg", frame)
    return encoded.tobytes() if ok else None
