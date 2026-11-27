# Caja V3 · prototipo (fase 0)

Punto de venta en Rust + Tauri 2 con interfaz React + NexFluid. Antes de trabajar aquí, lee
[`../docs/CONTEXTO_SESION.md`](../docs/CONTEXTO_SESION.md): decisiones, estado, cómo arrancarlo
en otra PC y cómo llegan los cambios de NexFluid (`vendor/`).

La v3 usa su **propia base** (`datos/ventas_v3.db` en desarrollo); los datos de la v2 se importan:

```bash
python3 scripts/crear_base_demo.py     # fuera de la caja: una base de la v2 con datos inventados
python3 -I scripts/copiar_base_real.py # en la caja: copia de solo lectura de la base de la v2 (no se sube)
(cd ../nucleo && cargo run --bin importar_v2 -- ../app/datos/ventas_copia.db ../app/datos/ventas_v3.db)
# Después, para REimportar conservando permisos, botones, códigos y correcciones de la v3:
./scripts/reimportar_v2.sh                # con la caja v3 cerrada; guarda la base anterior con fecha
npm install && npm run tauri dev
```
