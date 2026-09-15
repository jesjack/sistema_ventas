@echo off
cd /d "%~dp0"

:: Abre camera_viewer contra el DVR real (los valores por defecto de
:: DVRClient, ver camera_viewer\dvr_client.py). A diferencia de bash, en
:: cmd.exe las variables set quedan pegadas para el resto de la ventana --
:: si esta misma consola ya corrio antes run_camera_viewer_emulated.bat,
:: sin este limpiado camera_viewer seguiria apuntando al emulador.
set "DVR_HOST="
set "DVR_USER="
set "DVR_PASSWORD="
set "DVR_RTSP_PORT="

".venv\Scripts\python.exe" -m camera_viewer
