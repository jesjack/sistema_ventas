#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SOURCE_DIR/open_system.desktop"
SHARE_DIR="$SOURCE_DIR/share"
VENV_DIR="$SOURCE_DIR/.venv"
REQUIREMENTS_FILE="$SOURCE_DIR/requirements.txt"

if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "No se encontró el archivo fuente: $SOURCE_FILE" >&2
    exit 1
fi

# Ningun usuario debe abrir main.ods en modo solo-lectura de LibreOffice.
# main.ods se regenera por completo (no se edita in-place) cada vez que se
# abre el sistema, via prebake_ventas.py -> doc.save(), asi que el owner y
# permisos resultantes dependen solo de quien lo ejecuta y del umask -- no
# hay forma de "arreglarlo una vez" tocando el archivo. Por eso se ajusta
# aqui, con dos capas, sin depender de ningun grupo especifico (para poder
# migrar el sistema a otra PC sin tener que recrear grupos ahi):
#   1. chmod inmediato sobre lo que ya existe en share/.
#   2. ACL por defecto en share/ para que TODO archivo/carpeta que se cree
#      ahi en el futuro (incluido cada main.ods regenerado) nazca ya con
#      permiso de escritura para "otros", sin importar el umask del proceso
#      que lo crea.
# Entorno virtual separado tanto del Python embebido de LibreOffice como
# del python3 del sistema -- ahi corren camera_viewer y prebake_ventas.py
# (ver camera_viewer/launcher.py y open_system.sh). Crearlo/actualizarlo
# aqui significa que cada sync deja las dependencias al dia sin un paso
# manual aparte.
ensure_python_venv() {
    if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
        echo "Aviso: no se encontro $REQUIREMENTS_FILE, no se creo/actualizo el entorno virtual." >&2
        return
    fi

    if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
        if ! command -v python3 >/dev/null 2>&1; then
            echo "Aviso: 'python3' no esta instalado; no se pudo crear el entorno virtual en $VENV_DIR." >&2
            return
        fi

        echo "Creando entorno virtual en $VENV_DIR..."
        if ! python3 -m venv "$VENV_DIR"; then
            echo "Aviso: no se pudo crear el entorno virtual en $VENV_DIR (?esta instalado el paquete 'python3-venv' de tu distro?)." >&2
            return
        fi
    fi

    echo "Instalando dependencias de $(basename "$REQUIREMENTS_FILE") en $VENV_DIR..."
    if ! "$VENV_DIR/bin/python3" -m pip install --disable-pip-version-check -r "$REQUIREMENTS_FILE"; then
        echo "Aviso: fallo la instalacion de dependencias en $VENV_DIR." >&2
    fi
}

fix_share_permissions() {
    if [[ ! -d "$SHARE_DIR" ]]; then
        echo "Aviso: no se encontró $SHARE_DIR, no se ajustaron permisos de escritura." >&2
        return
    fi

    # -R toca todo lo que pueda; algunas subcarpetas (p.ej. share/logs, creada
    # por un proceso root) no son nuestras y fallaran aqui, pero ya vienen en
    # 0777 por su cuenta asi que no necesitan este ajuste. Por eso no se
    # valida el codigo de salida de estos dos comandos, sino el resultado real
    # sobre share/ (que es donde main.ods se recrea en cada apertura).
    chmod -R o+rwX "$SHARE_DIR" 2>/dev/null || true

    local share_mode
    share_mode="$(stat -c '%A' "$SHARE_DIR")"
    if [[ "${share_mode:8:1}" != "w" ]]; then
        echo "Aviso: $SHARE_DIR no quedo con permiso de escritura para 'otros' (?eres dueno de esa carpeta?)." >&2
    fi

    if ! command -v setfacl >/dev/null 2>&1; then
        echo "Aviso: 'setfacl' no esta instalado (paquete 'acl'); no se pudo fijar el permiso por defecto en $SHARE_DIR. El ajuste inmediato ya se aplico, pero un main.ods regenerado en el futuro podria volver a abrirse en modo solo-lectura para otros usuarios." >&2
        return
    fi

    setfacl -R -d -m other::rwX "$SHARE_DIR" 2>/dev/null || true
    if ! getfacl "$SHARE_DIR" 2>/dev/null | grep -q '^default:other::rw'; then
        echo "Aviso: no se pudo fijar el ACL por defecto de escritura en $SHARE_DIR (?el filesystem soporta ACLs?). El ajuste inmediato ya se aplico, pero un main.ods regenerado en el futuro podria volver a abrirse en modo solo-lectura para otros usuarios." >&2
    fi
}

fix_share_permissions
ensure_python_venv

copy_to_dir() {
    local target_dir="$1"
    local owner_user="${2:-}"
    local owner_group="${3:-}"
    local target_file="$target_dir/$(basename "$SOURCE_FILE")"

    mkdir -p "$target_dir"

    if [[ -n "$owner_user" && -n "$owner_group" ]]; then
        install -D -m 0644 -o "$owner_user" -g "$owner_group" "$SOURCE_FILE" "$target_file"
    else
        cp "$SOURCE_FILE" "$target_file"
    fi
}

resolve_desktop_dir() {
    local home_dir="$1"
    local config_file="$home_dir/.config/user-dirs.dirs"
    local desktop_dir=""

    if [[ -f "$config_file" ]]; then
        desktop_dir="$(HOME_BASE="$home_dir" awk -F'=' '/^XDG_DESKTOP_DIR=/{gsub(/"/, "", $2); gsub(/\$HOME/, ENVIRON["HOME_BASE"], $2); print $2; exit}' "$config_file")"
    fi

    if [[ -n "$desktop_dir" ]]; then
        printf '%s\n' "$desktop_dir"
        return 0
    fi

    if [[ -d "$home_dir/Escritorio" ]]; then
        printf '%s\n' "$home_dir/Escritorio"
        return 0
    fi

    printf '%s\n' "$home_dir/Desktop"
}

# Plantilla para usuarios nuevos.
copy_to_dir /etc/skel/Desktop
copy_to_dir /etc/skel/Escritorio

# Usuarios para los que fallo la copia, para reportar al final sin que un
# solo tropiezo (permisos raros, home inaccesible, etc.) frene el resto.
failed_users=()

# Usuario actual que invocó sudo, si aplica.
if [[ -n "${SUDO_USER:-}" ]]; then
    sudo_passwd_entry="$(getent passwd "$SUDO_USER" || true)"
    if [[ -n "$sudo_passwd_entry" ]]; then
        sudo_home_dir="$(printf '%s\n' "$sudo_passwd_entry" | cut -d: -f6)"
        sudo_primary_group="$(printf '%s\n' "$sudo_passwd_entry" | cut -d: -f4 | xargs getent group | cut -d: -f1)"
        if [[ -n "$sudo_home_dir" && -n "$sudo_primary_group" ]]; then
            copy_to_dir "$(resolve_desktop_dir "$sudo_home_dir")" "$SUDO_USER" "$sudo_primary_group" \
                || failed_users+=("$SUDO_USER")
        fi
    fi
fi

# Usuarios ya creados: copiar a los escritorios más comunes.
# Nota: set -e no detiene un bucle while por si solo cuando el comando que
# falla esta combinado con "||" -- por eso cada copia se maneja asi en vez de
# dejar que un solo usuario problematico aborte el resto del barrido.
while IFS=: read -r user home_dir _rest; do
    [[ -n "$home_dir" ]] || continue
    [[ "$home_dir" == /home/* ]] || continue
    [[ -d "$home_dir" ]] || continue

    primary_group="$(getent passwd "$user" | cut -d: -f4 | xargs getent group | cut -d: -f1)"
    if [[ -n "$primary_group" ]]; then
        copy_to_dir "$(resolve_desktop_dir "$home_dir")" "$user" "$primary_group" \
            || failed_users+=("$user")
    else
        failed_users+=("$user")
    fi
done < <(getent passwd)

echo "Sincronización completada desde: $SOURCE_FILE"

if [[ ${#failed_users[@]} -gt 0 ]]; then
    echo "Aviso: no se pudo copiar el icono para estos usuarios: ${failed_users[*]}" >&2
fi
