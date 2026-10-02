# Cómo arrancaría la V3

Equivalente, para la V3, de la sección 1 de `mapa_v2.md` («Cómo arranca hoy»). Documento de
trabajo: se corrige cuando se decidan D4 y D5. Escrito el 2026-09-30 a partir de `../README.md`,
`mapa_v2.md`, `diagrama_flujo_v2.md` y el código de `v_2`.

## Lo que se da por hecho

- Hay dos procesos con papeles fijos, iguales en Linux y Windows, y se comunican por un socket
  local:
  - **UNO**: el Python de LibreOffice, con solo `uno` y la biblioteca estándar. Pinta la hoja y
    captura teclas.
  - **App**: el venv instalado desde `pyproject.toml`. Tiene la lógica, la base, las
    impresoras, los usuarios, el lanzador y todas las ventanas (Qt).
- **D1:** Enter, escáner y teclas se capturan dentro de Calc con `XKeyHandler`. Desaparecen
  `keyboard` y `sudo`.
  - **Suposición:** el handler corre en un proceso Python remoto (la opción 1 de D1, que es la
    que se midió y funcionó). Si al final tuviera que ir dentro de soffice (opción 2), el proceso
    UNO dejaría de ser un proceso aparte y los árboles de abajo cambian.
- Todos los diálogos son Qt en App. D6 (el foco) se ve favorable.
- La instalación es idéntica en ambos sistemas. LibreOffice es una dependencia declarada: no se
  empaqueta. Se usan convenciones existentes: entry points de `pyproject.toml`, rutas de datos
  estándar por sistema y un grupo del sistema creado por el instalador.
- Hay un solo archivo de log por ejecución para todo el sistema, con tracebacks en texto plano y
  sin `rich`.

Siguen **pendientes** D2, D3, D4 y D5. El arranque depende sobre todo de **D5** (quién lanza a
quién) y **D4** (prebake). Por eso abajo van dos árboles, uno por cada opción de D5, y dentro de
cada uno se marcan las ramas de D4 y D3.

## 1. Árbol de procesos

### Opción D5-A: el lanzador de App abre LibreOffice y el proceso UNO (recomendada)

```
sistema-ventas                           (entry point [project.gui-scripts] del venv;
 │                                         acceso en el menú del sistema / menú Inicio)
 └─ App: lanzador
     ├─ abre el log de esta ejecución      → lo hereda cada hijo (variable de entorno)
     ├─ instancia única POR USUARIO        (candado en la carpeta de ejecución del usuario)
     ├─ una sola caja activa en el equipo  → «el último gana», ver nota 4 y D8 del mapa
     ├─ prepara main.ods de este usuario   (copia de la plantilla instalada)
     │   ├─ si D4 = prebake: la hornea con odfpy, dentro de App, con el modo en memoria
     │   └─ si D4 = en vivo: copia la plantilla vacía
     ├─ .venv: camera_viewer.archiver      (siempre, en segundo plano; como hoy, sin tocarlo)
     ├─ soffice --accept=pipe,name=<por usuario>;urp; --norestore main.ods
     │     (hijo de App: App conoce su pid y su código de salida)
     ├─ Python de LibreOffice: proceso UNO (solo uno + stdlib)
     │   ├─ recibe por argumentos: nombre del pipe, dirección y token del socket de App
     │   ├─ se conecta a soffice (con reintentos mientras abre) y al socket de App
     │   ├─ registra el XKeyHandler (Enter, escáner, Tab)
     │   ├─ si D3 = (b): registra un XActionListener por botón
     │   │  si D3 = (a): macros Basic del documento + .evt en la carpeta de ejecución del usuario
     │   ├─ si D4 = en vivo: pinta las tablas con las filas que le manda App
     │   └─ vigila el documento y avisa a App si se cierra o muere
     ├─ bucle de la App: servicios, ControladorVenta, botones, ventanas Qt
     │   ├─ .venv: camera_viewer           (botón VER CÁMARAS)
     │   └─ admin_botones                  (botón ADMINISTRAR ADMINS; proceso aparte como hoy,
     │                                       o ventana de la propia App: fuera de este documento)
     └─ al terminar soffice: App decide en memoria
         ├─ cierre normal          → fin
         ├─ cambio de modo         → vuelve a «prepara main.ods» con el modo nuevo
         └─ caída                  → política de relanzamiento (contador en memoria)
```

Notas:

1. **Sin `modo_sistema.json`, `relanzar.flag` ni `relanzamientos_por_fallo.json`.** En la V2
   existen porque cada vuelta es un `main.py` nuevo, hijo de soffice, y el único proceso que
   sobrevive es `open_system.sh`. Aquí App es el padre y sobrevive a soffice, así que el modo,
   la orden de relanzar y el contador de caídas viven en memoria. «El arranque desde el icono
   siempre entra en modo normal» deja de ser una regla que hay que proteger: sale solo.
2. **Si solo muere el proceso UNO**, App lo nota porque se corta el socket y puede relanzar solo
   ese proceso, sin cerrar LibreOffice. En la V2 eso no se puede: si `main.py` muere, la hoja
   queda abierta y sin nadie que la atienda.
3. **Un `main.ods` por usuario.** `main.ods` no guarda datos: se rehace en cada apertura (ver
   `vigilar_documento`). Con una copia por usuario en su carpeta de caché, desaparecen:
   - el `main.ods` compartido en `share/`;
   - el `chmod`/ACL de `fix_share_permissions`;
   - el caso de abrirlo en «solo lectura» porque otro usuario lo tiene abierto.

   El lock huérfano se vuelve trivial. App sabe si su soffice sigue vivo porque es su hijo, así
   que puede borrar el lock sin adivinar, o simplemente escribir una copia nueva.
4. **Instancia única — resuelto en D8 del mapa (2026-09-30).** En la V2,
   `asegurar_instancia_unica` existe por el puerto 2002: es único en todo el equipo, y `main.py`,
   que corre como root, podía acabar conectado al LibreOffice de otro usuario. Con un pipe por
   usuario y sin root esa causa desaparece, pero **«una sola caja activa por equipo» sí es regla
   del negocio** (un cajón, una impresora, un escáner). Además resuelve un caso real: la empleada
   que se va y deja su sesión abierta.
   - Por usuario: una sola instancia, con un candado del SO.
   - Por equipo: «el último gana». La App nueva le pide a la anterior, por un punto de encuentro
     en la carpeta de datos compartida, que se cierre en orden. Nada de `/proc`, señales ni root,
     y funciona igual en Windows.
5. **El pipe cambia lo medido en D1.** La medición de D1 se hizo por socket TCP (puerto 2097).
   El pipe con nombre debería ser igual o más rápido, pero hay que repetir la medición del ritmo
   de teclas con él antes de darlo por bueno.
6. **Abrir `main.ods` a mano no arranca nada**: con D5-A, el documento no lanza procesos. Con
   D3 = (b) ni siquiera lleva macros. Así desaparece de raíz el caso de `hoja_desactualizada`
   (2026-09-24).
7. **Log único.** App crea el archivo y lo pasa a cada hijo. La forma convencional es que App
   capture la salida estándar y de errores de cada hijo que lanza (UNO, archivador,
   camera_viewer, admin_botones) y la escriba en ese archivo con el nombre del proceso y su pid.
   Así no hay dos procesos escribiendo en el mismo archivo a la vez, y los fallos tempranos de
   UNO (antes de conectarse al socket) tampoco se pierden.
8. **Encontrar LibreOffice sin rutas fijas.**
   - Linux: `soffice` en el `PATH` y `/usr/bin/python3`, que debe poder importar `uno` (paquete
     `python3-uno`).
   - Windows: la ruta de instalación que LibreOffice registra en el registro
     (`HKLM\SOFTWARE\LibreOffice\UNO\InstallPath`, a verificar), de donde salen `soffice.exe` y
     `python.exe`.
   - En los dos: una opción de configuración para sobrescribirla.

   App lo comprueba al arrancar y, si falta algo, muestra un aviso claro en Qt.
9. **Perfil de LibreOffice (a medir).** Para que soffice sea de verdad hijo de App y no le pase
   el archivo a otra ventana de LibreOffice ya abierta por el mismo usuario, se puede usar un
   perfil propio: `-env:UserInstallation=...` en la carpeta de datos del usuario. Así también
   quedan fijas las opciones que el POS necesita, como la seguridad de macros si D3 = (a). El
   costo es que la primera apertura crea el perfil y tarda unos segundos más.

### Opción D5-B: la macro `Main` del documento sigue lanzando Python

```
acceso directo del sistema
 └─ lanzador fino (sigue haciendo falta un proceso exterior)
     ├─ si D4 = prebake: hornea main.ods antes de abrirlo (necesita saber el modo → archivo)
     ├─ limpia el lock huérfano            (sin saber qué soffice es de quién, como hoy)
     └─ soffice --accept=... main.ods      (espera a que cierre; relanza si hay bandera)
         └─ macro Basic Module1.Main       (necesita macros del documento habilitadas)
             └─ Shell: Python de LibreOffice → proceso UNO   (sin sudo; ruta resuelta, no fija)
                 ├─ busca o arranca App      → App no es padre de nadie: descubrimiento por
                 │                              un archivo en la carpeta de ejecución del usuario
                 ├─ App: .venv camera_viewer.archiver, camera_viewer, admin_botones
                 └─ al cerrar: App escribe modo / bandera; el lanzador fino relanza
```

Notas:

1. **Se conservan los archivos de estado entre vueltas**: el modo, la bandera de relanzar y el
   contador de caídas, porque ningún proceso de Python sobrevive a soffice.
2. **Abrir `main.ods` a mano sigue arrancando el sistema**: el caso de `hoja_desactualizada`
   hay que seguir cubriéndolo.
3. **Siguen las rutas dentro del documento.** `Main` debe saber dónde está el Python de
   LibreOffice y el código de UNO. Hoy son rutas fijas, y ya hay dos copias distintas de
   `Module1` (ver «Discrepancias encontradas»).
4. **El log único es más difícil**: el proceso UNO nace antes que App y no es su hijo.
5. Lo único que se ahorra frente a D5-A es que el documento siga siendo la forma de entrar.
   Pero como el lanzador exterior hace falta de todos modos (para el prebake y el bucle de
   relanzar), no se ahorra un proceso.

### Recomendación sobre D5 y D4

- **D5-A.** Casi todo el estado en archivos de la V2, la mayor parte de `open_system.sh`, la
  macro `Main`, el caso de `hoja_desactualizada` y la dificultad del log único vienen de que el
  padre de todo es un script de shell y el Python nace dentro de soffice. Con App como padre,
  todo eso desaparece o se vuelve trivial. Además, «un entry point que abre la aplicación» es
  justo la convención que pide el README.
- **D4, sin recomendación fuerte.** Con D5-A las dos opciones caben igual de bien:
  - **Conservar el prebake** es lo seguro: ya funciona y `odfpy` pasa a ser una dependencia más
    de App.
  - **Pintar en vivo** permitiría cambiar de modo sin cerrar LibreOffice: App le manda a UNO
    «pinta la tabla del día X». Así, `ver_ventas` y REGRESAR dejarían de relanzar.

  Depende de cuánto tarde pintar en vivo en la máquina de la tienda. Se decide midiendo, como
  dice el mapa.

## 2. V2 → V3

«Depende» indica que el destino cambia según una decisión pendiente. Si no se aclara otra cosa,
la columna V3 supone D5-A.

| Pieza del arranque V2 | V3 | Nota |
|---|---|---|
| `open_system.sh` / `.bat` (bucle, espera a soffice) | **Desaparece** | Lo reemplaza el entry point `sistema-ventas` de App. Con D5-B quedaría un lanzador fino. |
| `open_system.desktop` + `sync_open_system_desktop.sh` (copia a cada escritorio, `/etc/skel`, «Permitir lanzamiento») | **Cambia** | El instalador pone una entrada en el menú del sistema (Linux) y un acceso directo en el menú Inicio (Windows). Las entradas del menú no piden «confiar» como los `.desktop` del escritorio. |
| `.venv` en la carpeta del proyecto + `requirements.txt` | **Cambia** | Venv instalado desde `pyproject.toml`. |
| `prebake_ventas.py` | **Depende (D4)** | Si se queda, pasa a ser una función de App, sin proceso ni log propios. |
| `share/main.ods` compartido | **Cambia** (propuesta) | Plantilla instalada, de solo lectura, más una copia por usuario en su caché. |
| Limpieza del lock huérfano | **Desaparece o se vuelve trivial** | App sabe si su soffice vive. Con D5-B sigue como hoy. |
| `--accept` por el puerto TCP 2002 | **Cambia** (propuesta) | Pipe con nombre por usuario. Hay que volver a medir D1 (nota 5). |
| `relanzar.flag` | **Desaparece** (D5-A) | Bucle en memoria de App. |
| `modo_sistema.json` | **Desaparece** (D5-A) | El modo vive en memoria. Hoy lo leen `main.py` y el prebake. |
| `relanzamientos_por_fallo.json` | **Desaparece** (D5-A) | Contador en memoria; la política (2 en 600 s) se queda. |
| `asegurar_instancia_unica` (`/proc`, señales, `zenity`, solo Linux) | **Cambia** | Instancia única por usuario, más «una caja activa por equipo, el último gana» con cierre pedido, en los dos sistemas (nota 4, D8 del mapa). |
| `sudo` + `visudo.md` | **Desaparece** | Decidido por D1. |
| Hook global de `keyboard` | **Desaparece** | Decidido por D1 (`XKeyHandler`). |
| Macro Basic `Module1.Main` | **Desaparece** (D5-A) | Con D5-B se queda, pero sin rutas fijas. |
| `TPV_PrepararComunicacion`, `TPV_LimpiarBotones`, resto de `Module1` | **Depende (D3)** | Con D3 = (b) el documento no lleva macros. |
| `TPV_VerificarVersionModulo` | **Depende (D3/D5)** | Sin macros no hace falta. Hoy tampoco detecta la diferencia entre las dos copias (ver discrepancias). |
| Rutas absolutas fijas (`/home/jesjack/...`, `C:\Users\jesjack\...`) | **Desaparecen** | Entry points, rutas estándar por sistema y búsqueda de LibreOffice (nota 8). |
| `share/logs/events/` en 0777 | **Depende (D3)** | Con (a) pasa a la carpeta de ejecución del usuario, sin permisos abiertos (sin root ya no hace falta). Con (b) desaparece. |
| `fix_share_permissions` (`chmod -R o+rwX`, ACL por defecto) | **Cambia** | Grupo del sistema creado por el instalador para la carpeta de datos compartida (`ventas.db`). |
| `share/ventas.db` | **Cambia de lugar** | Carpeta de datos compartida estándar (p. ej. `/var/lib/...` en Linux, `%ProgramData%\...` en Windows), con escritura para el grupo. |
| `rich.traceback.install` | **Desaparece** | Tracebacks de stdlib en los dos procesos. |
| `logs/debug/`, `output.log`, `share/logs/prebake/`, `logs/admin_botones/`… | **Cambian** | Un solo archivo por ejecución (nota 7). |
| `hoja_desactualizada` | **Desaparece** (D5-A) | Con D5-B se queda. |
| `camera_viewer.archiver` al arrancar | **Se queda** | Lo lanza el lanzador de App en lugar de `main.py`. Sin tocar el archivador. |
| `camera_viewer` (VER CÁMARAS) | **Se queda** | Lo lanza App. Sin cambios en cámaras. |
| `admin_botones` (ADMINISTRAR ADMINS) | **Se queda** | Lo lanza App. Que sea una ventana de la propia App no es parte del arranque y no se decide aquí. |
| Python de LibreOffice (`python.exe` en Windows, `/usr/bin/python3` + `python3-uno` en Linux) | **Se queda** | Solo para el proceso UNO, sin paquetes de pip. Su versión la fija LibreOffice o la distro: el código UNO debe ser compatible con la más vieja de las dos. |
| Registro de usuario, seguimiento de sesión, plantilla de botones | **Se quedan** | En App, en el mismo orden, después de conectar con UNO. |

## Discrepancias encontradas

1. **Las dos copias de `Module1` declaran la misma versión.** El mapa ya dice que el `Module1`
   del repo lanza `/opt/python_global/bin/python` y la copia dentro de `main.ods` lanza
   `/usr/bin/python3`. Lo confirmé leyendo el ZIP (`Basic/Standard/Module1.xml`). Además, la
   copia de `main.ods` redirige la salida a `output.log` y la del repo no. Pero las dos declaran
   `TPV_MODULE_VERSION = 2`, así que `TPV_VerificarVersionModulo` no puede detectar la
   diferencia. Esa verificación además solo corre desde `TPV_PrepararComunicacionMacro`, que se
   invoca cuando Python publica los botones, no desde `Main`.
2. **El prebake también lee el modo.** El mapa ubica `modo_sistema.json` solo en `leer_modo` de
   `main.py` (nodo 8). `prebake_ventas.py` también llama a `leer_modo()` para decidir qué tablas
   hornea (las normales o la del día). Por eso, en la V2 el modo tiene que estar en disco
   *antes* de abrir soffice. Importa para D4 y D5.
3. **Prebake y LibreOffice no apuntan al mismo archivo fuera de producción.** El mapa menciona
   las rutas absolutas fijas. El detalle que falta: `open_system.sh` hornea el `main.ods`
   relativo a su propia carpeta, pero abre siempre `/home/jesjack/sistema_ventas/v_2/share/main.ods`.
   En cualquier copia que no sea la de producción (como este worktree), el prebake y LibreOffice
   trabajan sobre archivos distintos.
