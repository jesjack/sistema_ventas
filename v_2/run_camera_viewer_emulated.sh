#!/bin/bash
cd "$(dirname "$0")"

# Levanta el emulador local del DVR (cameras/dvr_emulator) y abre
# camera_viewer apuntandole a el en vez de al DVR real -- para probar
# calendario/busqueda de grabaciones sin tocar produccion. Mismo venv que
# el resto del proyecto (necesita cv2/numpy para el emulador y
# PySide6/opencv para camera_viewer, todo ya instalado ahi).
EMULATOR_HOST=127.0.0.1
EMULATOR_HTTP_PORT=8080
# 554 (el puerto real de RTSP) es privilegiado (pide root en Linux); 8554
# es un puerto cualquiera que cualquier usuario puede abrir. dvr_client.py
# ya sabe usar este valor via DVR_RTSP_PORT (ver mas abajo), asi que "Ver
# en vivo" funciona igual contra el emulador -- eso si, hace falta ffmpeg
# instalado para que el PLAY del RTSP realmente sirva video (el emulador
# avisa solo si no lo encuentra; el resto de este script no depende de el).
EMULATOR_RTSP_PORT=8554
EMULATOR_USER=nancy
EMULATOR_PASSWORD=2409

.venv/bin/python3 -m cameras.dvr_emulator \
    --host "$EMULATOR_HOST" \
    --http-port "$EMULATOR_HTTP_PORT" \
    --rtsp-port "$EMULATOR_RTSP_PORT" \
    --user "$EMULATOR_USER" \
    --password "$EMULATOR_PASSWORD" &
EMULATOR_PID=$!

# Si el emulador no pudo arrancar (puerto ya ocupado, etc.) no tiene caso
# seguir -- camera_viewer arrancaria sin nada real a lo que conectarse.
sleep 1
if ! kill -0 "$EMULATOR_PID" 2>/dev/null; then
    echo "El emulador no pudo arrancar (¿el puerto $EMULATOR_HTTP_PORT ya esta en uso?)." >&2
    exit 1
fi

DVR_HOST="$EMULATOR_HOST:$EMULATOR_HTTP_PORT" \
DVR_USER="$EMULATOR_USER" \
DVR_PASSWORD="$EMULATOR_PASSWORD" \
DVR_RTSP_PORT="$EMULATOR_RTSP_PORT" \
    .venv/bin/python3 -m camera_viewer &
APP_PID=$!

# Se apagan emulador y camera_viewer salga como salga este script (cierre
# normal de la ventana, Ctrl+C, o que alguien mate el script desde afuera)
# -- referenciar ambos PIDs aqui, aunque APP_PID recien se asigno arriba,
# funciona porque las comillas simples retrasan la expansion hasta que el
# trap de verdad se dispare, momento en el que ya existen las dos.
trap 'kill "$EMULATOR_PID" "$APP_PID" 2>/dev/null' EXIT

wait "$APP_PID"
