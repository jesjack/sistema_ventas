@echo off
cd /d "%~dp0"

:: Levanta el emulador local del DVR (cameras\dvr_emulator) y abre
:: camera_viewer apuntandole a el en vez de al DVR real -- para probar
:: calendario/busqueda de grabaciones sin tocar produccion. Mismo venv que
:: el resto del proyecto (necesita cv2/numpy para el emulador y
:: PySide6/opencv para camera_viewer, todo ya instalado ahi).
set "EMULATOR_HOST=127.0.0.1"
set "EMULATOR_HTTP_PORT=8080"
:: 554 es el puerto real de RTSP; 8554 es un puerto cualquiera, sin pedir
:: privilegios de administrador. dvr_client.py ya sabe usar este valor via
:: DVR_RTSP_PORT (ver mas abajo), asi que "Ver en vivo" funciona igual
:: contra el emulador -- eso si, hace falta ffmpeg instalado para que el
:: PLAY del RTSP realmente sirva video (el emulador avisa solo si no lo
:: encuentra; el resto de este script no depende de el).
set "EMULATOR_RTSP_PORT=8554"
set "EMULATOR_USER=nancy"
set "EMULATOR_PASSWORD=2409"

:: Ventana aparte con titulo unico: cmd.exe no da un PID facil de un
:: proceso en segundo plano, asi que se cierra despues por su titulo.
start "DVR Emulator Test" ".venv\Scripts\python.exe" -m cameras.dvr_emulator --host %EMULATOR_HOST% --http-port %EMULATOR_HTTP_PORT% --rtsp-port %EMULATOR_RTSP_PORT% --user %EMULATOR_USER% --password %EMULATOR_PASSWORD%

:: Le da un momento a arrancar antes de lanzar camera_viewer.
timeout /t 1 /nobreak >nul

set "DVR_HOST=%EMULATOR_HOST%:%EMULATOR_HTTP_PORT%"
set "DVR_USER=%EMULATOR_USER%"
set "DVR_PASSWORD=%EMULATOR_PASSWORD%"
set "DVR_RTSP_PORT=%EMULATOR_RTSP_PORT%"
".venv\Scripts\python.exe" -m camera_viewer

:: Cierra la ventana del emulador al terminar camera_viewer (cierre normal
:: o error) -- sin esto quedaria corriendo de fondo indefinidamente.
taskkill /FI "WINDOWTITLE eq DVR Emulator Test" /T /F >nul 2>&1
