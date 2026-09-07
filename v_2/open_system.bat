@echo off
cd /d "%~dp0"

set "TPV_MODO_JSON=share\logs\modo_sistema.json"
set "TPV_RELANZAR_FLAG=share\logs\relanzar.flag"
set "TPV_PRIMERA_VUELTA=1"

:loop
:: Salvaguarda: una apertura "de arranque" (doble clic, reinicio de la
:: maquina) siempre entra en modo normal, sin importar en que modo se quedo
:: la sesion anterior. Solo una vuelta interna de este mismo loop (via
:: relanzar.flag) conserva el modo recien escrito. Nota: el chequeo va sin
:: parentesis a proposito -- "::" dentro de un bloque if (...) rompe el
:: parser de cmd.exe.
if "%TPV_PRIMERA_VUELTA%"=="1" if exist "%TPV_MODO_JSON%" del "%TPV_MODO_JSON%"
set "TPV_PRIMERA_VUELTA=0"

:: Pre-hornea main.ods (estructura + ventas del dia) antes de abrir soffice.
:: Si falla, no bloquea la apertura: main.py detecta que no hay pre-horneado
:: valido y reconstruye la hoja en vivo como antes.
python prebake_ventas.py

:: Abre LibreOffice y ESPERA a que cierre por completo (sin "start"): esta
:: espera bloqueante es la senal de "ya cerro" para el siguiente prebake, y
:: evita que este mismo proceso herede un PATH modificado por el Python
:: embebido de LibreOffice (el bug que hacia fallar prebake_ventas.py al
:: relanzarse desde dentro del proceso de soffice).
"C:\Program Files\LibreOffice\program\soffice.exe" --accept="socket,host=localhost,port=2002;urp;" share\main.ods

if exist "%TPV_RELANZAR_FLAG%" (
    del "%TPV_RELANZAR_FLAG%"
    goto loop
)
