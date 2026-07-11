#!/bin/bash
# Este comando abre tu archivo abriendo simultáneamente el puerto 2002
libreoffice --accept="socket,host=localhost,port=2002;urp;" /home/jesjack/sistema_ventas/v_2/share/main.ods &
# env GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb libreoffice --accept="socket,host=localhost,port=2002;urp;" /home/jesjack/sistema_ventas/v_2/share/main.ods
