#!/bin/bash
cd "$(dirname "$0")"

# Pre-hornea main.ods (estructura + ventas del dia) antes de abrir soffice.
# Si falla, no bloquea la apertura: main.py detecta que no hay pre-horneado
# valido y reconstruye la hoja en vivo como antes.
python3 prebake_ventas.py

# Este comando abre tu archivo abriendo simultáneamente el puerto 2002
libreoffice --accept="socket,host=localhost,port=2002;urp;" /home/jesjack/sistema_ventas/v_2/share/main.ods &
# env GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb libreoffice --accept="socket,host=localhost,port=2002;urp;" /home/jesjack/sistema_ventas/v_2/share/main.ods
