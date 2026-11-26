#!/usr/bin/env bash
# Lleva a la caja lo que haya en la rama de NexFluid de la caja (ver CONTEXTO_SESION.md §5):
# compila, empaqueta foundation/core/components/react como 0.9.0-caja.N desde una copia temporal
# (nunca `npm version` dentro del repo de NexFluid), reemplaza los .tgz de vendor/, instala y
# BORRA LA CACHÉ DE VITE: sin eso, la app sigue sirviendo la versión anterior (pasó el 2026-11-26).
#
# Uso: ./empaquetar_nexfluid.sh            (usa ~/nexfluid, rama jesjack/feat/caja-v3)
#      NEXFLUID=/otra/ruta ./empaquetar_nexfluid.sh
# Después: reiniciar `npm run tauri dev`.
set -euo pipefail

APP="$(cd "$(dirname "$0")" && pwd)"
NEXFLUID="${NEXFLUID:-$HOME/nexfluid}"
RAMA="jesjack/feat/caja-v3"
VENDOR="$APP/vendor"

actual="$(grep -o 'caja\.[0-9]*\.tgz' "$APP/package.json" | head -1 | sed 's/caja\.\([0-9]*\)\.tgz/\1/')"
[ -n "$actual" ] || { echo "No encontré la versión caja.N en package.json" >&2; exit 1; }
siguiente=$((actual + 1))
echo "NexFluid: caja.$actual -> caja.$siguiente (rama $RAMA)"

cd "$NEXFLUID"
[ "$(git branch --show-current)" = "$RAMA" ] || { echo "NexFluid no está en $RAMA" >&2; exit 1; }
[ -z "$(git status --porcelain -- packages)" ] || { echo "NexFluid tiene cambios sin guardar en packages/" >&2; exit 1; }
nice -n 10 npm run build:lib >/dev/null

temporal="$(mktemp -d)"
trap 'rm -rf "$temporal"' EXIT
for p in foundation core components react; do
  mkdir -p "$temporal/$p"
  cp -r "packages/$p/package.json" "packages/$p/dist" "packages/$p/README.md" "packages/$p/LICENSE" "$temporal/$p/"
  (cd "$temporal/$p" && node -e "const fs=require('fs');const p=JSON.parse(fs.readFileSync('package.json'));p.version='0.9.0-caja.$siguiente';fs.writeFileSync('package.json',JSON.stringify(p,null,2)+'\n')" \
    && npm pack -q --pack-destination "$VENDOR" >/dev/null)
done

cd "$APP"
for p in foundation core components react; do rm -f "$VENDOR/nexfluid-$p-0.9.0-caja.$actual.tgz"; done
sed -i "s/0\.9\.0-caja\.$actual\.tgz/0.9.0-caja.$siguiente.tgz/g" package.json
nice -n 10 npm install >/dev/null
rm -rf node_modules/.vite
echo "Listo: caja.$siguiente instalado y caché de Vite borrada. Reinicia la app (npm run tauri dev)."
