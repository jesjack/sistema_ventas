#!/bin/bash
cd "$(dirname "$0")"

MODO_JSON="share/logs/modo_sistema.json"
RELANZAR_FLAG="share/logs/relanzar.flag"
primera_vuelta=1

while true; do
    if [[ "$primera_vuelta" == "1" ]]; then
        # Salvaguarda: una apertura "de arranque" (icono de escritorio, reinicio
        # de la maquina) siempre entra en modo normal, sin importar en que modo
        # se quedo la sesion anterior. Solo una vuelta interna de este mismo
        # loop (via relanzar.flag) conserva el modo recien escrito.
        rm -f "$MODO_JSON"
    fi
    primera_vuelta=0

    # Pre-hornea main.ods (estructura + ventas del dia) antes de abrir soffice.
    # Si falla, no bloquea la apertura: main.py detecta que no hay pre-horneado
    # valido y reconstruye la hoja en vivo como antes.
    python3 prebake_ventas.py

    # Abre LibreOffice y ESPERA a que cierre por completo (sin "&" en segundo
    # plano): esta espera bloqueante es la senal de "ya cerro" para el
    # siguiente prebake, y evita que este mismo proceso herede un PATH
    # modificado por el Python embebido de LibreOffice.
    libreoffice --accept="socket,host=localhost,port=2002;urp;" /home/jesjack/sistema_ventas/v_2/share/main.ods

    if [[ -f "$RELANZAR_FLAG" ]]; then
        rm -f "$RELANZAR_FLAG"
        continue
    fi

    break
done
