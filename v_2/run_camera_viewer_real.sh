#!/bin/bash
cd "$(dirname "$0")"

# Abre camera_viewer contra el DVR real (los valores por defecto de
# DVRClient, ver camera_viewer/dvr_client.py) -- se limpian las DVR_* por
# las dudas, en caso de que esta misma terminal ya las haya exportado
# antes para probar contra el emulador (run_camera_viewer_emulated.sh).
unset DVR_HOST DVR_USER DVR_PASSWORD DVR_RTSP_PORT

.venv/bin/python3 -m camera_viewer
