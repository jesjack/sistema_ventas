@echo off
:: Abre LibreOffice habilitando el puerto 2002 en segundo plano
start "" "C:\Program Files\LibreOffice\program\soffice.exe" --accept="socket,host=localhost,port=2002;urp;" main.ods
