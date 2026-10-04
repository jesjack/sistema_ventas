# Diagrama de instalación de la V3: índice y documentación

Los diagramas están en [`diagramas/`](diagramas/), en los archivos que empiezan con
`instalacion_`, uno por archivo `.mmd` (Mermaid puro). Siguen las mismas convenciones que el
flujo de la V3 (ISO 5807, colores y conectores): ver «Cómo leerlo» en
[`diagrama_flujo_v3.md`](diagrama_flujo_v3.md).

Fuente: D16, D19 y D20 de `mapa_v2.md` (2026-10-03), más D7, D8, D9 y D13 para el primer
arranque. **Todo se hace como administrador y para todo el equipo** (D20).

**Actores** (ver `instalacion_00_leyenda.mmd`):

- **Administrador.** Es una persona, no un proceso, pero aquí es un actor con su propio flujo:
  es quien teclea los tres pasos y responde lo que pregunta el paso 3.
- **SO y gestor de paquetes:** apt o winget, y el script oficial de uv.
- **uv.**
- **App:** el comando `sistema-ventas instalar` y el primer arranque de cada usuario.
- **En gris, Internet y el usuario.** Son los otros extremos de algunos pines, sin flujo propio.

## Archivos

| Archivo | Chip | Qué muestra |
|---|---|---|
| `instalacion_00_leyenda.mmd` | — | Colores de cada actor. |
| `instalacion_01_administrador_instalacion.mmd` | Administrador | Los tres pasos. El 1 difiere por sistema; el 2 lleva las variables de uv en rutas del sistema (`/opt/sistema-ventas` o Archivos de programa) y la etiqueta del repositorio (D20). |
| `instalacion_02_gestor_de_paquetes.mmd` | gestor | Instala uv (paso 1) y LibreOffice (cuando lo pide el paso 3), en la versión que ofrezca el sistema. |
| `instalacion_03_uv.mmd` | uv | `uv tool install` y `uv tool upgrade` desde el repositorio público, con su Python, en rutas del sistema. |
| `instalacion_04_app_instalar.mmd` | App | `sistema-ventas instalar`: LibreOffice, grupo `tpv_yaeli` y carpeta compartida (D19), usuarios del grupo, código de caja (D20) y acceso directo. |
| `instalacion_05_administrador_actualizacion.mmd` | Administrador | Actualizar: pedir que se cierre el sistema y repetir la instalación con la etiqueta nueva (o `uv tool upgrade`). |
| `instalacion_06_app_primer_arranque.mmd` | App | Primer arranque de cada usuario: candado, perfil propio de LibreOffice con ubicación de confianza y copia de `main.ods`. |
| `instalacion_99_placa.mmd` | — | Actores y cables entre pines. |

**El comando del paso 2** (D20). Una etiqueta por versión, desde el repositorio público:

```
uv tool install "git+https://github.com/jesjack/sistema_ventas@vX.Y.Z#subdirectory=v_3"
```

Se corre como administrador, con `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR` y `UV_PYTHON_INSTALL_DIR`
apuntando a rutas del sistema. Actualizar es el mismo comando con otra etiqueta, o
`uv tool upgrade`.

## Pines por chip

### Administrador

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `instalar_uv` | OUT | Comando del paso 1 | SO y gestor de paquetes | Terminal (script oficial o `winget`) |
| `uv_instalado` | IN | ¿Se instaló? | SO y gestor de paquetes | Salida del comando |
| `uv_tool_install` | OUT | Comando del paso 2, con la etiqueta y las variables de uv | uv | Terminal de administrador |
| `uv_tool_upgrade` | OUT | Comando de actualización | uv | Terminal de administrador |
| `uv_termino` | IN | ¿Se instaló o actualizó? | uv | Salida del comando |
| `instalar_sistema` | OUT | `sistema-ventas instalar` | App | Terminal de administrador |
| `pregunta_admin` | IN | Qué usuarios agregar al grupo, o el código de apertura de caja | App | Terminal |
| `respuesta_admin` | OUT | La respuesta | App | Terminal |
| `instalar_termino` | IN | Resumen o error | App | Salida del comando |

### SO y gestor de paquetes

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `instalar_uv` | IN | Comando | Administrador | Terminal |
| `instalar_paquete` | IN | Paquetes de LibreOffice que faltan | App | Subproceso (`apt`, `winget`) |
| `repositorio_datos` | IN | Paquetes | Internet | Red |
| `pedir_repositorio` | OUT | Pedido de paquetes | Internet | Red |
| `uv_instalado` | OUT | Resultado | Administrador | Salida del comando |
| `paquete_instalado` | OUT | Resultado | App | Código de salida del subproceso |

### uv

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `uv_tool_install` | IN | Etiqueta del proyecto a instalar | Administrador | Terminal |
| `uv_tool_upgrade` | IN | Proyecto a actualizar | Administrador | Terminal |
| `indice_datos` | IN | La etiqueta del repositorio, paquetes y, si hace falta, un Python | Internet (GitHub e índice de paquetes) | Red |
| `pedir_indice` | OUT | Pedido | Internet | Red |
| `uv_termino` | OUT | Resultado | Administrador | Salida del comando |

Almacenamiento: `UV_TOOL_DIR`, en una ruta del sistema, con el entorno del proyecto.

### App (`sistema-ventas instalar` y primer arranque)

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `instalar_sistema` | IN | Comando | Administrador | Terminal de administrador |
| `instalar_paquete` | OUT | Paquetes que faltan | SO y gestor de paquetes | Subproceso |
| `paquete_instalado` | IN | Resultado | SO y gestor de paquetes | Código de salida |
| `pregunta_admin` | OUT | Usuarios del grupo o código de caja | Administrador | Terminal |
| `respuesta_admin` | IN | La respuesta | Administrador | Terminal |
| `instalar_termino` | OUT | Resumen o error | Administrador | Salida del comando |
| `inicio` | IN | Argumentos del entry point | Usuario (menú) | Creación de proceso |

Almacenamiento:
- `sistema-ventas instalar` crea la carpeta de datos compartida con su grupo (D19), crea
  `ventas.db` si no existe, guarda el hash del código de caja (D20) y escribe el acceso directo.
- El primer arranque crea el candado, el perfil de LibreOffice y el `main.ods` del usuario.

## Verificación de pines

| # | Pin | De (OUT) | A (IN) | Mecanismo |
|---|---|---|---|---|
| 1 | `instalar_uv` | Administrador | SO y gestor de paquetes | Terminal |
| 2 | `uv_instalado` | SO y gestor de paquetes | Administrador | Salida del comando |
| 3 | `uv_tool_install` | Administrador | uv | Terminal |
| 4 | `uv_tool_upgrade` | Administrador | uv | Terminal |
| 5 | `uv_termino` | uv | Administrador | Salida del comando |
| 6 | `instalar_sistema` | Administrador | App | Terminal de administrador |
| 7 | `instalar_termino` | App | Administrador | Salida del comando |
| 8 | `pregunta_admin` | App | Administrador | Terminal |
| 9 | `respuesta_admin` | Administrador | App | Terminal |
| 10 | `instalar_paquete` | App | SO y gestor de paquetes | Subproceso |
| 11 | `paquete_instalado` | SO y gestor de paquetes | App | Código de salida |
| 12 | `pedir_repositorio` | SO y gestor de paquetes | Internet | Red |
| 13 | `repositorio_datos` | Internet | SO y gestor de paquetes | Red |
| 14 | `pedir_indice` | uv | Internet | Red |
| 15 | `indice_datos` | Internet | uv | Red |
| 16 | `inicio` | Usuario (menú) | App | Creación de proceso |

**Resultado:** los 16 cables tienen su OUT y su IN.

## Notas y discrepancias

D19 y D20 resolvieron las discrepancias de la ronda anterior:
- Instalación para todo el equipo con rutas del sistema.
- Versión mínima de LibreOffice por definir, probando versiones.
- Grupo `tpv_yaeli` y quién se agrega.
- Cerrar el sistema antes de actualizar en Windows.
- Origen del paquete en el repositorio público.

Quedan como notas:

1. **Volver a iniciar sesión (D19).** En Linux, cada usuario agregado al grupo vuelve a iniciar
   sesión una vez. Está como nota en `instalacion_04_app_instalar.mmd`.
2. **El paso 1 en Linux.** D20 pide todo como administrador y para todo el equipo, pero el
   script oficial de uv instala uv en la carpeta personal de quien lo corre. Eso basta para el
   administrador, que es quien usa uv; los usuarios solo usan `sistema-ventas`, que el paso 2 ya
   pone en `UV_TOOL_BIN_DIR`. Conviene confirmarlo al probar la instalación.
3. **Versión mínima de LibreOffice.** Mientras no se defina, `instalacion_04` solo comprueba
   que LibreOffice esté instalado y, en Linux, que `python3` importe `uno`. No compara la
   versión.

## Cómo se verificó

Con el mismo `verificar_iso.py` que el flujo de la V3, sobre los archivos `instalacion_*.mmd`
de `diagramas/` y este índice. Los criterios son los mismos (ver `diagrama_flujo_v3.md`); los
colores esperados de los pines son los de los actores de la instalación.
