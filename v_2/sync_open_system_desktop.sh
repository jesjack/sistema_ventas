#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SOURCE_DIR/open_system.desktop"

if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "No se encontró el archivo fuente: $SOURCE_FILE" >&2
    exit 1
fi

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
