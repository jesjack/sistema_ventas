"""Emulador local del DVR Dahua/Amcrest usado por los scripts de ../cameras.

Fase 1 (implementada): protocolo HTTP-CGI -- mediaFileFind.cgi, loadfile.cgi,
timeZone.cgi, configManager.cgi, sysinfo.cgi -- con Digest Auth real
(RFC 2617, qop=auth), igual que el DVR real.

Fase 2 (pendiente): servidor RTSP para el endpoint 'realmonitor' que usa
vivo.py.

Ejecutar con: python -m cameras.dvr_emulator
"""
