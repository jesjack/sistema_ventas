#!/bin/bash
# Este comando abre tu archivo abriendo simultáneamente el puerto 2002
libreoffice --accept="socket,host=localhost,port=2002;urp;" main.ods &

