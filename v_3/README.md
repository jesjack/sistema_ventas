# Sistema de ventas — V3

Versión en desarrollo. La versión en producción sigue siendo `v_2/` (rama `v2`).

## Objetivo

La V3 no busca funciones nuevas para quien usa la caja: el flujo de venta debe seguir siendo
igual de rápido y libre que en la V2 (productos escritos a mano, sin exigir códigos de barras ni
inventario). El objetivo es **compatibilidad, portabilidad y convenciones**:

- **Instalación idéntica en Linux y Windows.**
- **Usar herramientas y convenciones existentes** en lugar de soluciones propias para instalar,
  lanzar y administrar permisos multiusuario.

## Diseño acordado

Dos intérpretes con papeles fijos, iguales en ambos sistemas:

| Papel | Linux | Windows | Qué corre |
|---|---|---|---|
| Intérprete de LibreOffice | `/usr/bin/python3` + `python3-uno` | `python.exe` de LibreOffice | Solo el código que habla con Calc: `uno` + biblioteca estándar, **sin paquetes de pip**. |
| Intérprete de la app | venv creado desde `pyproject.toml` | igual | Todo lo demás: escáner, impresoras, códigos de barras, Qt, cámaras. |

Ambos procesos se comunican por un socket local. LibreOffice es una dependencia externa
declarada; no se empaqueta con el proyecto.

## Pasos propuestos

1. Mapa del corte: qué hace hoy el proceso de `v_2/main.py`, qué queda del lado UNO, qué pasa
   al venv y qué mensajes cruzan entre ambos.
2. `pyproject.toml` y un lanzador en Python que funcione igual en ambos sistemas.
3. Mover primero lo de menos riesgo (impresión de etiquetas); el cobro y el escáner, al final.
