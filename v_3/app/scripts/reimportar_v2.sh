#!/usr/bin/env bash
# Vuelve a importar la base REAL de la v2 a la v3 del prototipo, CONSERVANDO lo que solo vive en la
# v3 (permisos, botones, códigos de caja, correcciones del catálogo). Las ventas, sesiones y cortes
# de prueba de la v3 se descartan: la v2 es la oficial.
#
# 1. Copia la v2 en solo lectura (scripts/copiar_base_real.py → datos/ventas_copia.db).
# 2. Importa a una base nueva (datos/ventas_v3.nueva.db) con --conservar datos/ventas_v3.db.
# 3. Guarda la anterior como datos/ventas_v3.anterior-<fecha>.db (NO se borra) y pone la nueva.
#
# Cierra la caja v3 antes. Uso (desde v_3/app):  ./scripts/reimportar_v2.sh
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
DATOS="$APP/datos"
ACTUAL="$DATOS/ventas_v3.db"
NUEVA="$DATOS/ventas_v3.nueva.db"
ANTERIOR="$DATOS/ventas_v3.anterior-$(date +%Y-%m-%d_%H%M).db"

if pgrep -x caja >/dev/null; then
  echo "La caja v3 está abierta: ciérrala primero (tiene abierta la base)." >&2
  exit 1
fi
[ -f "$ACTUAL" ] || { echo "No existe $ACTUAL (para la primera importación usa importar_v2 sin --conservar)." >&2; exit 1; }
[ ! -e "$NUEVA" ] || { echo "Ya existe $NUEVA (¿quedó de un intento anterior?). Revísala y bórrala a mano." >&2; exit 1; }

python3 -I "$APP/scripts/copiar_base_real.py"
(cd "$APP/../nucleo" && CARGO_BUILD_JOBS=2 nice -n 10 cargo run -q --bin importar_v2 -- "$DATOS/ventas_copia.db" "$NUEVA" --conservar "$ACTUAL")
mv "$ACTUAL" "$ANTERIOR"
mv "$NUEVA" "$ACTUAL"
echo "Listo. La base anterior quedó en $ANTERIOR"
