#!/bin/bash
cd "$(dirname "$0")"

MODO_JSON="share/logs/modo_sistema.json"
RELANZAR_FLAG="share/logs/relanzar.flag"
LOCK_MAIN_ODS="share/.~lock.main.ods#"
# En share/logs/, no en logs/ a secas: es la carpeta con permisos de lectoescritura para
# todos los usuarios (ver fix_share_permissions en sync_open_system_desktop.sh; share/logs/events/
# ya usa el mismo patron). logs/prebake/ vivio ahi un rato el 2026-09-24 y quedo sin permiso de
# escritura para nadie mas que quien lo creo -- exactamente el mismo tipo de bug que el de
# ventas.db, esta vez introducido por el propio registro que se agrego ese dia para diagnosticar
# el primero.
PREBAKE_LOGS_DIR="share/logs/prebake"
PREBAKE_RUNS_TO_KEEP=200
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
# El pre-horneado no dejaba ningun rastro: si fallaba (o si alguien abria main.ods sin pasar por
# aqui), nadie se enteraba -- se descubrio el 2026-09-24 despues de que un usuario viera datos
# de horas antes sin ningun error visible. Un log por corrida, con quien y cuando, para que la
# proxima vez no haga falta reproducirlo en vivo para ver que paso.
ejecutar_prebake_con_registro() {
    mkdir -p "$PREBAKE_LOGS_DIR"

    local existentes
    existentes=("$PREBAKE_LOGS_DIR"/run_*.log)
    if [[ -e "${existentes[0]}" ]]; then
        local total=${#existentes[@]}
        if (( total > PREBAKE_RUNS_TO_KEEP - 1 )); then
            printf '%s\n' "${existentes[@]}" | sort | head -n "$(( total - (PREBAKE_RUNS_TO_KEEP - 1) ))" | xargs -r rm -f
        fi
    fi

    local archivo_log="$PREBAKE_LOGS_DIR/run_$(date +%Y%m%d_%H%M%S)_$(id -un).log"
    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] usuario=$(id -un) uid=$(id -u)"
        .venv/bin/python3 prebake_ventas.py
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] codigo de salida: $?"
    } > "$archivo_log" 2>&1
}

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
    ejecutar_prebake_con_registro

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
