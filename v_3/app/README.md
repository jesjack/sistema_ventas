# Caja V3 · prototipo (fase 0)

Punto de venta en Rust + Tauri 2 con interfaz React + NexFluid. Antes de trabajar aquí, lee
[`../docs/CONTEXTO_SESION.md`](../docs/CONTEXTO_SESION.md): decisiones, estado, cómo arrancarlo
en otra PC y cómo llegan los cambios de NexFluid (`vendor/`).

```bash
python3 scripts/crear_base_demo.py     # fuera de la caja (productos inventados)
python3 -I scripts/copiar_base_real.py # en la caja (copia de solo lectura; no se sube)
npm install && npm run tauri dev
```
