from __future__ import annotations

DEFAULT_HOST = "0.0.0.0"
DEFAULT_HTTP_PORT = 8080
DEFAULT_RTSP_PORT = 554
DEFAULT_FFMPEG_PATH = "ffmpeg"
DEFAULT_USER = "nancy"
DEFAULT_PASSWORD = "2409"
REALM = "Login to DVR"
CHANNELS = (1, 2, 3, 4)

# Mismos tonos que CHANNEL_COLORS en dvr_timeline_app.py (alla en hex para
# Tkinter; aqui en BGR, que es lo que espera OpenCV al dibujar).
CHANNEL_COLORS_BGR = {
    1: (250, 164, 96),
    2: (153, 211, 52),
    3: (36, 187, 251),
    4: (113, 113, 248),
}
