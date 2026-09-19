#!/bin/bash
cd "$(dirname "$0")"

MODO_JSON="share/logs/modo_sistema.json"
RELANZAR_FLAG="share/logs/relanzar.flag"
LOCK_MAIN_ODS="share/.~lock.main.ods#"
primera_vuelta=1

# LibreOffice deja "share/.~lock.main.ods#" mientras el documento esta abierto
# y, si soffice muere sin cerrar bien (corte de luz, kill, crash), el archivo
# queda huerfano: la siguiente apertura muestra el aviso y abre main.ods como
# "copia" (solo lectura / sin poder guardar). El lock no guarda PID, asi que
# la unica forma de saber si es un falso positivo es ver si hay algun
# soffice.bin de ESTE usuario vivo. Si lo hay, se deja el lock intacto: puede
# ser una instancia real.
# El filtro por usuario es a proposito: si el lock es de OTRO usuario, main.py
# (root, ver services/instancia_unica.py) lo desplaza justo despues de abrir,
# y dejar su lock aqui haria que este arranque muestre el aviso de "copia" y
# main.py nunca llegue a correr. Ese otro sistema se cierra enseguida y
# main.ods no persiste datos, asi que compartirlo unos segundos no cuesta nada.
limpiar_lock_huerfano() {
    [[ -e "$LOCK_MAIN_ODS" ]] || return 0

    if pgrep -u "$(id -u)" -x soffice.bin >/dev/null 2>&1; then
        echo "[lock] Hay una instancia de LibreOffice activa; se conserva $LOCK_MAIN_ODS"
        return 0
    fi

    echo "[lock] $LOCK_MAIN_ODS es huerfano (no hay instancia de LibreOffice); eliminandolo"
    rm -f "$LOCK_MAIN_ODS"
}

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
    # Se usa el venv del proyecto (no un "python3" suelto del PATH) para que
    # solo haga falta administrar dos interpretes en total: el embebido de
    # LibreOffice y este venv (tambien usado por camera_viewer).
    .venv/bin/python3 prebake_ventas.py

    limpiar_lock_huerfano

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
