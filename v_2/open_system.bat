@echo off
cd /d "%~dp0"

:: Pre-hornea main.ods (estructura + ventas del dia) antes de abrir soffice.
:: Si falla, no bloquea la apertura: main.py detecta que no hay pre-horneado
:: valido y reconstruye la hoja en vivo como antes.
python prebake_ventas.py

:: Abre LibreOffice habilitando el puerto 2002 en segundo plano
start "" "C:\Program Files\LibreOffice\program\soffice.exe" --accept="socket,host=localhost,port=2002;urp;" share\main.ods
