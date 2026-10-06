# Mapa de `v_2/main.py`: qué queda en LibreOffice y qué pasa al venv

Primer paso de la V3 (ver `../README.md`). Documento de trabajo: se corrige a medida que se
decide cada punto. Levantado sobre `v2` en `48c9980`, solo leyendo código.

**Leyenda de la propuesta**

- **UNO**: proceso de LibreOffice (solo `uno` + biblioteca estándar).
- **App**: proceso del venv.
- **Los dos**: cada proceso tiene su propia copia.
- **Decidir**: hay más de una opción razonable (ver la sección final).

## 1. Cómo arranca hoy

```
open_system.sh / .bat
 ├─ .venv/python prebake_ventas.py      → escribe share/main.ods (tablas + ventas del día) con odfpy
 ├─ borra el lock huérfano de main.ods
 └─ libreoffice --accept=port 2002 main.ods   (espera a que cierre; relanza si hay relanzar.flag)
     └─ macro Basic Module1.Main
         └─ sudo /usr/bin/python3 main.py      (Windows: python.exe de LibreOffice, sin sudo)
             └─ nucleo.arranque.ejecutar()
                 ├─ .venv: camera_viewer.archiver    (siempre, en segundo plano)
                 ├─ .venv: camera_viewer             (botón VER CÁMARAS)
                 └─ .venv: admin_botones             (botón ADMINISTRAR ADMINS)
```

Detalles del arranque que no se ven en el esquema:

- En la primera vuelta, `open_system.sh` borra `modo_sistema.json`, así que un arranque desde el
  icono siempre entra en modo normal.
- El lock de `main.ods` solo se borra si no hay ningún `soffice.bin` del mismo usuario.
- Antes del `Shell`, `Main` ejecuta `TPV_PrepararComunicacion` y `TPV_LimpiarBotones`.
- Hay rutas absolutas fijas (`/home/jesjack/...`, `C:\Users\jesjack\...`) en `open_system.sh`
  y en `Main`.
- El `Module1` del repo lanza `/opt/python_global/bin/python`; la copia dentro de `main.ods`
  (la que corre) lanza `/usr/bin/python3`. Es una diferencia conocida por el usuario. Las dos copias declaran
  `TPV_MODULE_VERSION = 2`, así que `TPV_VerificarVersionModulo` no detecta la diferencia (y solo
  corre desde `TPV_PrepararComunicacionMacro`, no desde `Main`).
- `open_system.sh` hornea el `main.ods` de su propia carpeta, pero abre siempre
  `/home/jesjack/sistema_ventas/v_2/share/main.ods`. Fuera de producción (por ejemplo en otro
  checkout), el prebake y LibreOffice usan archivos distintos.

Hoy ya son dos intérpretes: `main.py` (UNO, como root) y el `.venv` (prebake, cámaras,
admin_botones). El problema es que el lado UNO también carga paquetes externos.

**Paquetes externos que hoy importa el proceso de `main.py`**

| Paquete | Quién lo usa | Motivo |
|---|---|---|
| `keyboard` | `nucleo/arranque.py`, `services/scanner_detector.py` | Enter global y detección del escáner. Es lo que exige `sudo`. |
| ~~`gi` (Gtk, Wnck)~~ | `calc/calc_focus.py` | **En realidad no se usa:** solo lo importa, de forma local, `calc_esta_enfocado`, y nadie llama esa función. |
| `rich` | `main.py` | Tracebacks con variables locales. |
| `PIL`, `barcode`, `niimprint`, `serial` | `hardware/barcode_printer.py` | Etiquetas de código de barras. |
| `qrcode`, `win32print` | `hardware/ticket_printer.py` | Ticket y cajón de dinero. |

## 2. Nodos, en el orden en que corren

### 2.1 Arranque común (`main.py`, `ejecutar`)

| # | Nodo | Qué hace | Depende de | Propuesta |
|---|---|---|---|---|
| 1 | `activar_log_de_depuracion`, `activar_volcado_de_hilos` | Log por ejecución en `logs/debug/`; volcado de hilos con `SIGUSR1`. | stdlib | **Los dos** |
| 2 | `rich.traceback.install` | Tracebacks con variables locales, en cuadros y colores pensados para una persona. | `rich` | **Se reemplaza** por tracebacks legibles para una IA: texto plano sin colores ANSI ni dibujos de cuadros, completos (sin recortar), con las variables locales y con proceso, pid, hilo y hora. Solo stdlib (`traceback.TracebackException(..., capture_locals=True)` + `sys.excepthook`/`threading.excepthook`), así que va igual en **los dos** procesos y `rich` desaparece. |
| 3 | `asegurar_instancia_unica` | Un solo usuario del equipo a la vez: cierra el sistema de otro usuario y pide relanzar. Usa `/proc`, `pwd`, señales, `zenity`. | stdlib, pero solo Linux | **App** (lanzador). Falta equivalente en Windows. |
| 4 | `_iniciar_archivador_de_camaras` | Lanza `camera_viewer.archiver` en el venv. | subproceso | **App** (sin tocar cámaras: es de la otra instancia) |
| 5 | `conectar_libreoffice`, `obtener_documento_calc` | Se conecta por el puerto 2002 y busca `main.ods`. | `uno` | **UNO** |
| 6 | `SheetAdmin` | Protege/desprotege la hoja (`temporary_unlock`). | `uno` | **UNO** |
| 7 | `registrar_seguimiento_foco_calc` | Registra listeners de foco, pero su estado solo lo lee `calc_esta_enfocado`, que nadie llama. | `uno` | **Candidato a borrar** junto con `calc_esta_enfocado` y la rama `gi` |
| 8 | `leer_modo` | Decide el modo `normal` o `ventas_dia` a partir de `share/logs/modo_sistema.json`. También lo lee `prebake_ventas.py` antes de abrir soffice, así que el modo tiene que estar en disco antes del arranque. | stdlib | **App** decide; **UNO** recibe el modo que debe pintar |

### 2.2 Modo `ventas_dia` (solo lectura)

| # | Nodo | Qué hace | Propuesta |
|---|---|---|---|
| 9 | `VentasService().obtener_ventas(fecha)` | Lee las ventas del día elegido. | **App** |
| 10 | `attach_existing(...)` | Se engancha a la tabla que horneó el prebake. | **UNO** |
| 11 | Botón "REGRESAR AL SISTEMA PRINCIPAL" | Escribe el modo, pide relanzar y cierra LibreOffice. | Botón en **UNO**; la decisión de relanzar en **App** |

### 2.3 Modo normal

| # | Nodo | Qué hace | Depende de | Propuesta |
|---|---|---|---|---|
| 12 | `VentasService`, `UsuariosService`, `CatalogoService`, `CodigosBarrasService`, `BotonesService` (+ `esquema`, `base_datos`) | Todo el acceso a `share/ventas.db`. | `sqlite3` (stdlib) | **App**: un solo dueño de la base |
| 13 | `TableManager` + `table_modules/carrito.py` | Reglas del carrito y de la venta: sumar, cobrar, registrar, imprimir. Ya no dependen de UNO. | nada | **App** |
| 14 | `table_modules/core.py` + `view.py` (`Table`) | Pintar tablas en la hoja: colores, título, total, marcador de vacío. | `uno` | **UNO** |
| 15 | `_registrar_usuario` (`identidad`, `usuarios_service`) | Sincroniza usuarios con el SO y registra al actual; si falla, muestra un aviso. | `pwd`, `getent`, rama Windows | **App**, incluido el aviso (Qt) |
| 16 | `SeguimientoSesionSistema` | Hilo de latido de sesión en la base. | stdlib | **App** |
| 17 | `preparar_tablas` (+ `hoja_desactualizada`) | Se engancha a lo prehorneado o reconstruye en vivo. | `uno` | **UNO**; las filas se las da **App** |
| 18 | `AutocompletadoProductoHandler` | `XKeyHandler` en Calc: con Tab busca en el catálogo y abre el selector. | `uno` | **UNO** captura el Tab y escribe el producto elegido en B4; **App** busca en el catálogo y muestra el selector (Qt) |
| 19 | `otorgar_plantilla_a_usuario_nuevo` | Botones iniciales para un usuario nuevo. | base | **App** |
| 20 | `Contexto` | Bolsa de todo lo anterior, que reciben las acciones y el controlador. | — | Se parte en dos: contexto UNO y contexto App |
| 21 | `cargar_acciones` | Carga `acciones/*.py` dinámicamente. | stdlib | **App** (ver 2.4) |
| 22 | `ControladorVenta` (`on_enter`, `on_scan`, `_cobrar`) | El flujo de Enter: agregar al carrito, cobrar, registrar un código nuevo, abrir la caja con código. Ya recibe todo lo externo por el constructor. | inyectado | **App**; lo que hoy se inyecta (diálogos, foco, celda) pasa a ser mensajes a UNO |
| 23 | `scanner_detector` + `keyboard.add_hotkey("enter")` | Hook global de teclado: detecta Enter y distingue escáner de tecleo por el ritmo. | `keyboard`, root | **Decidir** (D1) |
| 24 | `es_libreoffice_calc_enfocado` (`calc/calc_window_focus.py`), `enfocar_celda_sin_azul` | Solo acepta Enter si el frame activo de LibreOffice es Calc (`isActive()`; si la consulta falla, devuelve True); devuelve el cursor a B4. | `uno` | **UNO**; la comprobación del foco sobra si D1 = XKeyHandler |
| 25 | `SheetButtonBridge` | Pide a Basic dibujar botones; Basic escribe un `.evt` por clic en `share/logs/events/` y Python lo sondea cada 0.5 s. | `uno`, Basic, archivos | **UNO**; **Decidir** el mecanismo (D3) |
| 26 | `BotonesDeLaHoja` (+ `revisar_cambios` en cada tick) | Qué botones ve el usuario y refrescar si admin_botones cambió algo. | base | **App** decide la lista; **UNO** la dibuja |
| 27 | `abrir_panel_admin` | Lanza admin_botones (Qt) en el venv. | subproceso | **App** |
| 28 | `vigilar_documento` | Sondea `documento.Title` cada segundo y apaga el "¿guardar cambios?". | `uno` | **UNO** avisa a App cuando el documento muere |
| 29 | `resolver_salida_del_documento` | ¿Cierre normal o caída? Política de relanzamientos. | archivos de `modo_sistema` | **App** (lanzador) |
| 30 | `terminar_libreoffice` | `desktop.terminate()`. | `uno` | **UNO**, por orden de App |

### 2.4 Acciones (`acciones/*.py`, botones de la hoja)

**Decidido (2026-09-29, propuesta del usuario): los diálogos pasan a Qt, en App.** Qt da más
libertad que los diálogos UNO y ya es la dirección de la V2 (admin_botones y camera_viewer).
UNO solo pinta lo que vive en la hoja. Riesgo por medir: el foco (ver D6).

| Acción | App (lógica + ventanas Qt) | UNO (solo la hoja) |
|---|---|---|
| `abrir_caja` | Abrir el cajón (impresora) y registrar el evento en la base. | Agregar la fila del evento a la tabla de ventas. |
| `autocompletado` | Editor del catálogo (Qt); leer y guardar el catálogo. | — |
| `cobrar_carrito` | Diálogo de cobro (Qt); calcular el total, registrar la venta, imprimir el ticket, marca `selling`. | Vaciar la tabla del carrito y agregar las filas a ventas. |
| `imprimir_codigo_de_barras` | Diálogo con vista previa en vivo y aviso de impresión (Qt); buscar el código; imprimir la etiqueta. | — |
| `limpiar_carrito` | Vaciar el estado del carrito. | Vaciar la tabla. |
| `ping` | Imprimir en el log. | — |
| `ver_camaras` | Lanzar camera_viewer; el aviso "Abriendo cámaras…" puede ser Qt. **No tocar** (otra instancia). | — |
| `ver_codigos_de_barras` | Ventana con la lista (Qt); leer los códigos. | — |
| `ver_ventas` | Diálogo de fecha (Qt); cambiar de modo y relanzar. | Pintar la tabla del día (modo `ventas_dia`). |

### 2.5 Módulos de soporte

| Módulo | Propuesta |
|---|---|
| `dialogs/_base.py` y todos los diálogos UNO | **Se reescriben en Qt, en App**; `_base.py` desaparece |
| `dialogs/formato.py`, `dialogs/parseo.py` (sin UNO) | **App**, se reusan tal cual con los diálogos Qt |
| `hardware/ticket_printer.py`, `hardware/barcode_printer.py` | **App** |
| `services/modo_sistema.py` (modo, `relanzar.flag`, intentos de relanzamiento) | **App** (lanzador) |
| `prebake_ventas.py` | Ya corre en el venv. **Decidir** si sigue existiendo (D4) |
| `libreofficeModules/Module1` (Basic) | **UNO**; **Decidir** si `Main` sigue lanzando Python (D5) |
| `ui/ventana_acciones.py` | Nadie lo importa: candidato a borrar |

## 3. Mensajes que cruzarían entre procesos (preliminar)

Con los diálogos en App, casi todo son **avisos de un solo sentido**. App ya no le pide a UNO
"muestra el diálogo y espérame": abre su propia ventana Qt y solo le manda a UNO qué pintar.

- **UNO → App:** `uno_listo` (conectado a soffice y a App, handlers registrados); se pulsó
  Enter (con el contenido de la fila de entrada y el ritmo de las teclas o el veredicto de
  escaneo, ver D10); Tab con el prefijo escrito; clic en el botón `id`; el documento se cerró o
  murió.
- **App → UNO:** pinta estas filas en la tabla de entrada, carrito o ventas (incluye el modo:
  `normal` o `ventas_dia` con su fecha); agrega una fila de evento; escribe este producto en B4;
  publica esta lista de botones; devuelve el foco a Calc y a B4; cierra LibreOffice.

Pines de detalle que agregó `diagrama_flujo_v3.md` (2026-10-02) y que este resumen no lista uno
por uno: `urp_conectar`/`urp_listo` (UNO ↔ soffice), `api_hoja`/`api_respuesta` (cada llamada
a la hoja), `tecla`/`tecla_respuesta` (si UNO consume la tecla) y `terminar_soffice` (App cierra
soffice si UNO no arranca en 30 s). La lista completa de 68 pines está en ese archivo.

## 4. Decisiones pendientes

- **D1. Enter y escáner — DECIDIDO (2026-09-29): dentro de LibreOffice, sin `keyboard`.**
  Lo propuso el usuario. Enter, escáner y teclas se capturan dentro de Calc con `XKeyHandler`,
  el mismo mecanismo que ya usa el autocompletado para Tab. Solo recibe teclas cuando Calc tiene
  el foco, así que desaparecen `keyboard`, `sudo` y el chequeo de foco, y funciona igual en Linux
  y Windows. La regla de `scanner_detector.is_scan()` (promedio ≤ 20 ms, hueco máximo ≤ 60 ms,
  desviación ≤ 15 ms, mínimo 3 teclas) es solo stdlib y se reusa.

  Queda por elegir **dónde corre el handler**, y eso se decide midiendo:
  1. **Python remoto** (como hoy el autocompletado: proceso aparte conectado por el puerto 2002).
     Riesgo: `KeyEvent` no trae marca de tiempo, así que la hora se toma al llegar al proceso
     Python, después del puente, con su retraso variable. Además, cada tecla es una llamada
     síncrona de ida y vuelta: LibreOffice espera la respuesta (consumida o no) antes de seguir,
     lo que podría frenar el tecleo del escáner.
  2. **Dentro de soffice**: una macro Python en el propio LibreOffice (misma API, mismo
     `scanner_detector`) o una macro Basic (`GetSystemTicks()`, en ms). La hora se toma dentro
     del proceso de LibreOffice, sin puente ni ida y vuelta. Si gana esta opción, el proceso UNO
     de la V3 podría ser directamente una macro Python dentro de soffice. Eso afecta D5.

  **Medición 1 (2026-09-30, Linux/Wayland, Python remoto por el puerto 2097, escáner real).**
  Script y datos crudos en `pruebas/d1_teclado/`.

  | Entrada | Teclas | Promedio entre teclas | Máximo | ¿`is_scan()` V2? |
  |---|---|---|---|---|
  | 7 escaneos (5 a 18 caracteres + Enter) | 6–18 | **16.0–19.6 ms** | 25.8–64.6 ms | 6 sí, 1 no |
  | 5 entradas a mano, lo más rápido posible | 5–12 | **86–172 ms** | 153–545 ms | todas no |

  Conclusiones:
  - **Leer el teclado con UNO funciona.** Códigos completos y en orden; los escaneos repetidos
    son idénticos. Enter llega al handler con la celda en edición.
  - **El puente deforma el ritmo tecla por tecla.** Las teclas llegan en parejas casi pegadas
    (0.5–2 ms) seguidas de un hueco de unos 25 ms. Un escaneo tuvo un hueco de 64.6 ms (puente
    "en frío") y la regla V2 lo habría tomado como tecleo a mano. A mano también hay intervalos
    de 1 ms (dos teclas casi juntas). Así que la desviación, el hueco máximo y cualquier
    intervalo individual no sirven.
  - **El promedio de todo el tramo sí separa bien:** ≤ 19.6 ms el escáner contra ≥ 86 ms a
    mano, más de 4 veces de margen.

  **Regla propuesta** (sustituye a la de la V2): es escaneo si el tramo termina en Enter, tiene
  **al menos 3 caracteres antes del Enter** (igual que `MIN_LENGTH = 3` en la V2, que tampoco
  cuenta el Enter) y el promedio entre teclas es ≤ 40 ms. Como red de seguridad, ningún hueco pasa
  de 100 ms: el escáner llegó a 64.6; a mano nunca bajó de 153. Un hueco mayor de 100 ms también
  reinicia el tramo.

  Diferencias con la V2 que explican el cambio:
  - **La V2 tenía la hora real de cada tecla.** `record_key` recibía `event.time` de
    `keyboard` (marca de tiempo del evento de teclado del sistema), así que las reglas tecla por
    tecla (hueco máximo ≤ 60 ms, desviación ≤ 15 ms) medían al escáner. El `KeyEvent` de UNO no
    trae marca de tiempo; solo se sabe cuándo llegó a Python, y eso mide también al puente.
  - **En la V2, un hueco mayor de 60 ms reiniciaba el tramo** (`_reset_history_for_new_segment`).
    Con el puente, ese corte habría partido el escaneo del hueco de 64.6 ms. Por eso el reinicio
    pasa a 100 ms, el mismo valor que la red de seguridad.

  Pendiente:
  - Repetir en Windows.
  - Confirmar con el tecleo de la dueña, que será igual o más lento (a favor de la regla).
  - Medir con el POS cargado.
  - Probar el handler dentro de soffice solo si en algún caso falla el remoto.

  **Hallazgo aparte (también afecta a la V2):** el código `SN:GLH…` llega como `SNÑGLH…`. Casi
  seguro el lector usa distribución de teclado de EE. UU.: su `:` cae en la tecla de la `Ñ`
  española. Se corrige configurando el lector en español o traduciendo esos caracteres.

- **D2. Lógica de negocio — DECIDIDO (2026-10-02): toda en App.** Controlador, carrito,
  servicios, acciones y ventanas. UNO solo pinta y captura.
- **D3. Clics en botones — DECIDIDO (2026-10-02): opción (a), Basic + `.evt`.** El usuario ya
  probó en la V2 crear botones y enlazar sus eventos desde Python con UNO, y fue inviable. Lo
  documentado (`registerScriptEvent`) apunta a una macro dentro de LibreOffice, no a un proceso
  externo. Un listener puesto desde fuera al control visible se pierde cuando LibreOffice
  recrea los controles. El clic lo sigue recibiendo Basic, que escribe un `.evt`; los archivos
  pasan a la carpeta de ejecución del usuario. Ver D13.
- **D4. Prebake — DECIDIDO (2026-10-02): se queda.** Reduce el tiempo de carga del documento: no
  hay que rehacer las tablas con UNO en cada apertura. Lo hace App, con odfpy, antes de abrir
  soffice, sobre la copia de `main.ods` de cada usuario (D7) y con el modo en memoria.
- **D5. Quién lanza a quién — DECIDIDO (2026-09-30): opción A, App es el proceso padre.**
  El lanzador de App abre soffice y el proceso UNO, y lanza los demás hijos. El estado de
  arranque (modo, relanzamientos) vive en la memoria de App, no en archivos
  (`modo_sistema.json`, `relanzar.flag`). La macro `Main` deja de lanzar Python. Detalle en
  `arranque_v3.md`.
- **D6. Foco entre las ventanas Qt y Calc.** Un diálogo UNO es modal sobre Calc y recibe el
  teclado solo. Una ventana Qt de otro proceso no. Riesgos:
  - **Robo de foco bloqueado.** GNOME en Wayland, y también Windows, impiden que un proceso en
    segundo plano tome el foco. El diálogo de cobro podría aparecer sin teclado, y el monto se
    escribiría en la hoja.
  - **Regreso del foco a Calc.** Pasa lo mismo al cerrar el diálogo.
  - **Modalidad.** Con el diálogo abierto se podría seguir usando Calc. Esto se resuelve en App,
    ignorando Enter mientras haya un diálogo abierto (como hoy hace `selling`).

  **Evidencia (2026-09-30, del usuario):** admin_botones y camera_viewer, lanzados desde un clic
  en Calc, aparecen al frente. El caso es favorable; falta confirmarlo con el diálogo de cobro
  lanzado desde un Enter, no desde un clic.

  Pista original: admin_botones y camera_viewer ya se abren desde un clic en Calc. Si sus ventanas
  aparecen al frente con el teclado activo, el caso es favorable. Hay que medirlo con el diálogo
  de cobro, que se usa en cada venta y se teclea de inmediato. Opciones si falla: token de
  activación (`xdg-activation`) pasado desde LibreOffice, sesión X11/XWayland para App, o dejar
  solo el cobro en UNO.
- **D7. `main.ods` por usuario — DECIDIDO, con una condición del usuario.** Ningún usuario puede
  quedarse con una copia desactualizada. Propuesta que lo garantiza: `main.ods` deja de ser un
  archivo que se conserva. Es una plantilla instalada con el programa, y App la copia de nuevo a
  la carpeta del usuario **en cada arranque** (pesa ~27 KB), así que no hay copia vieja que
  sincronizar. Se van el archivo compartido, sus permisos y el lock huérfano entre usuarios.
- **D8. Instancias.**
  - **Por usuario: una sola, siempre.** Un candado de instancia única en App, con bloqueo del
    SO que se libera solo si el proceso muere. Solo App lanza el proceso UNO, así que tampoco
    puede haber dos procesos UNO.
  - **Por equipo: una sola caja activa** (regla de negocio: un cajón, una impresora, un escáner).
    Se conserva "el último que abre se queda con la caja", que resuelve la sesión que alguien
    dejó abierta. Cambio respecto a la V2: el que llega toma el turno y le **avisa** a la
    instancia anterior que se cierre en orden, sin root ni `kill` (detalle abajo).
  - **Turno de caja como token en `ventas.db` (2026-10-02).** Una fila con el turno vigente
    (número, usuario, sesión, desde). Tomar la caja = `UPDATE turno = turno + 1` en una
    transacción (atómica en SQLite). El token del otro **no se expira: se invalida solo**,
    porque deja de ser el vigente. **No hace falta esperar** a la App anterior. La nueva toma el
    turno de inmediato, marca la sesión anterior como "desplazada por X" y le avisa. Antes de
    cada acción con efecto (vender, imprimir, abrir el cajón, escribir en la base) y de forma
    periódica, cada App comprueba que su número sigue vigente. Si no, no hace nada y se cierra.
    Una acción que ya había empezado en ese instante (p. ej. imprimir el ticket de una venta ya
    registrada) termina sin problema.
  - **Carrito a medias de la sesión desplazada: se pierde**, como en la V2. Las ventas son rápidas
    y el carrito no importa.

- **D9. Sin rutas fijas.** Ni `/home/jesjack/...` ni `C:\Users\jesjack\...` en ningún archivo.
  - Las rutas del programa se derivan de dónde está instalado.
  - Las de datos, de las rutas estándar de cada sistema (`platformdirs`).
  - LibreOffice se busca en el PATH (Linux) o en el registro (Windows).
  - Así el prebake y soffice nunca pueden usar archivos distintos, como hoy en `open_system.sh`.
- **D10. ¿Quién decide si fue escaneo? — DECIDIDO (2026-10-02): App.** UNO toma las horas de
  llegada y las manda; App aplica la regla. La precisión es la misma: las horas se toman en UNO
  en ambos casos. Así el código prescindible de UNO queda centralizado en el venv.
  - **Mejora futura: identificar el dispositivo que tecleó.**
    - Windows: Raw Input, sin administrador.
    - Linux/Wayland: una aplicación no puede saberlo por diseño. Hay que leer `/dev/input` con
      una regla `udev`, que pondría el paso de administrador de D16. Con eso App podría
      quedarse con el lector y los códigos ni llegarían a Calc.
    - Son dos implementaciones y hay que reconocer qué dispositivo es el lector. Se pospone: la
      regla por tiempos ya está medida.
- **D11. Cámaras — DECIDIDO (2026-10-02): siguen siendo un proceso aparte**, que no se cierra con
  el POS. **Objetivo nuevo de la V3: integrarlas con las ventas.**
  - Marcas de cada venta en la línea de tiempo de camera_viewer.
  - En el POS, abrir las cámaras en el momento exacto de una venta.
  - Pines: App → camera_viewer "abrir en fecha y hora"; camera_viewer lee de `ventas.db`, solo
    lectura, las horas de las ventas del día.
  - El interior de camera_viewer lo implementa la instancia de cámaras.
- **D12. admin_botones — DECIDIDO (2026-10-02): diálogo Qt dentro de App**, como el resto de las
  ventanas de la V3. Hay un solo dueño de `ventas.db`, respeta el turno de caja (D8) y desaparece
  el sondeo de `revisar_cambios`. Falta decidir la estructura del código de App (D18).
- **D13. Macros Basic — DECIDIDO (2026-10-02): se quedan, como actor dentro de soffice.** Crean
  los botones, reciben los clics (D3) y devuelven el foco a Calc. `Main` desaparece: la App lanza
  todo (D5). Para que las macros corran sin avisos ni configuración a mano, la App arranca soffice
  con un perfil propio de LibreOffice y marca la carpeta del `main.ods` del usuario como ubicación
  de confianza (**hay que probarlo**).
- **D14. Tab — DECIDIDO (2026-10-02): por defecto NO se consume.** El cursor siempre pasa a la
  celda de la derecha, como en Excel; requisito de usabilidad del usuario. UNO confirma la edición
  de B4, manda el texto a App y devuelve "no consumida". App busca: sin coincidencias, nada; con
  coincidencias, muestra el selector Qt y, al elegir, pide a UNO escribir el producto en B4. El
  cursor ya queda en PRECIO.
  - **Interruptor de ajuste:** un parámetro de configuración (`consumir_tab`) que App le pasa a
    UNO al conectarse decide si el Tab se consume. Sirve para los ajustes finales del prototipo.
    Consumirlo devuelve el comportamiento de la V2 (cursor en B4).
- **D15. Cobro rápido sin ticket — DECIDIDO (2026-10-02).** Tercera opción en el diálogo de
  cobro, con atajo de teclado, para clientes que pagan y se van sin esperar ticket. Registra la
  venta con recibido = total y cambio = 0, y abre el cajón (`open_cash_drawer()`) sin imprimir.
  Se guarda toda la información posible: la marca "sin ticket", el usuario y la sesión.
- **D16. Instalación — DECIDIDO (2026-10-02; el usuario delegó la elección).** Con `uv`.
  - Paso 1: instalar `uv`. Es lo único que difiere: script oficial en Linux, `winget` en Windows.
  - Paso 2, idéntico en los dos: `uv tool install` del proyecto. `uv` también pone el Python de
    la App.
  - Paso 3, idéntico, una sola vez con permisos de administrador: el comando de instalación del
    sistema. Instala o verifica LibreOffice con el gestor de paquetes (`apt install
    libreoffice-calc python3-uno` / `winget install TheDocumentFoundation.LibreOffice`), con una
    versión mínima (producción usa 25.2). Crea la carpeta de datos compartida con su grupo o
    permisos y pone el acceso directo.
  - Actualizar: `uv tool upgrade`. Las migraciones de la base corren al arrancar.
- **D19. Permisos de los datos compartidos — DECIDIDO (2026-10-03): un grupo del sistema**, que es
  la convención para datos compartidos entre varios usuarios. El usuario pidió "lo más usual".
  - Linux: la carpeta de datos (`ventas.db`, el log, el turno) pertenece a un grupo, con el bit
    setgid y sin permisos para "otros". Se reutiliza el grupo `tpv_yaeli` que ya existe (hoy:
    jesjack, nancy, miriamyaelicastanedaaparicio, emilymaya).
  - Windows: un grupo local con permisos sobre la carpeta en `C:\ProgramData`.
  - Lo crea y configura el paso de administrador de D16 (`sistema-ventas instalar`), que también
    agrega usuarios nuevos al grupo; en Linux, la empleada agregada vuelve a iniciar sesión una vez.
  - Desaparecen `fix_share_permissions`, `chmod o+rwX` y la ACL `other::rwX` de la V2.
  - En la V2 el grupo dio problemas por `sudo` (`f7ffb55`: al bajar de root a usuario, Python no
    restauraba los grupos). En la V3 no hay root: cada proceso nace del usuario y hereda sus
    grupos.
- **D20. Ajustes de la tercera ronda — DECIDIDO (2026-10-03).**
  - **Turno:** cada App lo comprueba cada ~3 s. No hay pin de aviso a la App desplazada: se entera
    en su siguiente comprobación.
  - **Basic y los `.evt`:** UNO le pasa a la macro la ruta de la carpeta de ejecución del usuario
    al invocarla (D9: sin rutas fijas).
  - **Log de las cámaras:** al arrancar, App escribe `log_actual` (ruta del log de esta ejecución)
    en su carpeta de ejecución. camera_viewer revisa antes de escribir si cambió; si cambió,
    escribe en el log viejo "continúa en <nuevo>" y en el nuevo "viene de <viejo>", y sigue en el
    nuevo. Sin App abierta, sigue en el último. Propuesta del usuario más el mecanismo; lo
    implementa la instancia de cámaras.
  - **Instalación para todo el equipo, como administrador:** `/opt/sistema-ventas` en Linux,
    `Archivos de programa` en Windows (`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_PYTHON_INSTALL_DIR`
    apuntando a rutas del sistema). Instalar y actualizar se hace como administrador.
  - **Origen:** el repositorio público `jesjack/sistema_ventas`, una etiqueta por versión, y un
    solo comando: `uv tool install "git+https://github.com/jesjack/sistema_ventas@vX.Y.Z#subdirectory=v_3"`.
  - **Versión mínima de LibreOffice:** se decide probando versiones viejas, descargadas del
    archivo oficial y extraídas aparte con perfil propio (sin tocar producción). Pruebas: UNO, el
    teclado de D1, pintar tablas y macros. **Tarea pendiente, con el prototipo.**
  - **Código de apertura de caja:** sale del código fuente (en la V2 está en `nucleo/config.py`,
    público en GitHub). Se guarda como hash (`hashlib`, stdlib) en la configuración de `ventas.db`,
    nunca en texto plano ni en un `.env`. **Corregido por D21:** no lo pide la instalación ni lo
    conoce el desarrollador. Lo configura un usuario con el permiso "abrir caja sin límite".
- **D21. Papeles, permisos y apertura de caja — DECIDIDO (2026-10-06).** Sale del uso real: la
  dueña le daba el código a cada empleada nueva, y la empleada lo usaba una vez al día para
  contar el cambio. El código no autorizaba nada.
  - **Desarrollador:** quien instala (hoy jesjack). Tiene el menú de administración (botones,
    configuración, permisos) y configura el sistema para que la dueña lo tenga fácil. Sustituye a
    "administrador" y a `ADMIN_RAIZ` de la V2.
  - **Permisos por usuario, no puestos.** Pensado para más locales en el futuro: nada lleva
    nombres en el código. Los asigna el desarrollador desde su menú, como la visibilidad de
    botones de la V2.
    - **"Abrir caja sin límite"** (hoy: nancy, la dueña, y miriamyaelicastanedaaparicio, su hija,
      de confianza): botón "Abrir caja" siempre disponible, sin código.
    - **Empleada** (hoy: emilymaya): botón "Abrir caja" habilitado **una vez al día por caja y
      solo antes de la primera venta**, para contar el cambio. Hoy no hay segundas empleadas; si
      hay cambio de turno, se revisa.
  - **Aperturas fuera de esa ventana** (cambiar dinero a un vecino, pagar a un repartidor, una
    devolución, recontar): la empleada pulsa "Abrir caja" y se pide el **código de autorización**,
    que solo conocen los usuarios con "abrir caja sin límite". Una de ellas lo teclea o se lo
    dice en ese momento. Así el código vuelve a ser una autorización real.
  - El código se guarda como hash (D20). Lo configura y lo cambia un usuario con "abrir caja sin
    límite", desde su propio menú; si no hay código, se le pide la primera vez que entra. El
    desarrollador no lo conoce ni lo pide la instalación.
  - **Código de un solo uso (decidido 2026-10-06).** Si la dueña se lo dicta a la empleada, la
    empleada lo conoce y deja de autorizar; el sistema no puede saber quién lo tecleó. Por eso,
    después de usarse, el código **queda bloqueado**. Si la empleada lo intenta de nuevo, ve
    "Código usado; pide a Nancy o a Miriam que abran la caja". La siguiente vez que entra
    cualquier usuario con "abrir caja sin límite", se le pide un código nuevo y se le muestra el
    uso anterior (quién, cuándo, autorizada con código). Mientras tanto, la empleada sigue
    vendiendo (cada venta con ticket abre el cajón) y la dueña puede abrir en persona sin código.
  - Mejora futura, solo si hiciera falta autorizar a distancia con frecuencia: códigos TOTP
    (cambian cada 30 s en una app del teléfono de la dueña; estándar, implementable con la
    stdlib). Por ahora no.
  - Cada apertura se registra con usuario, sesión, hora y cómo se autorizó (permiso, ventana
    diaria o código). Nunca se guarda el código; en la V2 `autorizaciones_codigos` lo guarda en
    texto plano.
- **D22. App de larga vida y cámaras como hijo — DECIDIDO (2026-10-06).** Amplía D5 y D11.
  - App es el proceso de larga vida y dueña de todo: POS (LibreOffice + UNO) y cámaras. No se
    cierra mientras quede algo abierto; cuando se cierra lo último, App termina.
  - Instancia única por usuario (D8): si App ya corre, el acceso directo le avisa que vuelva a
    abrir LibreOffice, en vez de abrir otra App.
  - camera_viewer es **proceso hijo de App**, aislado (OpenCV y el video son lo más frágil; un
    fallo no tumba la caja), conectado por el mismo tipo de canal que UNO. App sabe si está
    abierto, le pide saltar a una fecha y hora y le pasa las ventas. Sustituye a "camera_viewer
    sobrevive a App" de D11.
  - **Logs:** una ejecución = la vida de App. Al reabrir LibreOffice se sigue en el mismo archivo
    con una marca (`=== LibreOffice abierto de nuevo (sesión N) ===`); solo se cambia de archivo
    al cambiar el día, con el enlace "continúa en / viene de". El `log_actual` de D20 deja de
    hacer falta: camera_viewer escribe por el canal de App.
- **Archivador de cámaras — fuera de la V3 (2026-10-02).** Por la salud del DVR. En la V2 ya está
  desactivado con `share/runtime/archivador_desactivado`: el POS lo lanza, pero sale sin tocar
  el DVR.
- **D17. Teclas durante un diálogo — DECIDIDO (2026-10-02).** En la V2 no ha sido un problema: los
  diálogos no avanzan sin el dato (monto, código). En la V3:
  - Los Enter que llegan a App con un diálogo abierto se descartan y se anotan en el log como
    "tecla inusual", igual que los dobles Enter en menos de ~150 ms.
  - Regla de diseño de los diálogos Qt: Enter activa el botón por defecto, así que ningún
    diálogo acepta con Enter si falta el dato. La opción "sin ticket" (D15), que abre el cajón y
    no se puede deshacer, **nunca** es el botón por defecto: solo con su atajo o un clic.
- **D18. Estructura del código de App — DECIDIDO (2026-10-02).**
  - **Bucle:** App corre dentro del bucle de Qt, en el hilo principal (lo único soportado por Qt
    para la parte gráfica). Las tareas bloqueantes (imprimir, abrir el cajón, esperas largas) van
    en hilos aparte con tiempo máximo y se conectan con señales de Qt. Se probó que un error en
    un slot no mata el bucle (PySide6 6.11.2: imprime el error y sigue). También se discutió
    poner Qt en un hilo propio: no está soportado oficialmente. La variante soportada (Qt como
    "servidor de ventanas" en el hilo principal y nuestro bucle en otro) quedó descartada por
    el usuario a favor de esta, más simple.
  - **Protecciones:**
    - `dominio/` y `servicios/` no importan Qt: se prueban sin Qt y no dependen de él.
    - Nada lento en el hilo de Qt.
    - Un vigilante en otro hilo: si el bucle no responde en unos segundos, vuelca al log en qué
      línea está cada hilo, como `nucleo/diagnostico.py` de la V2.
    - `sys.excepthook`/`threading.excepthook` con tracebacks legibles para IA.
  - **Paquete:** `src/sistema_ventas/` con `nucleo/`, `dominio/`, `servicios/`, `ventanas/`,
    `hardware/`, `acciones/`, `puente/`, `proceso_uno/` (corre en el Python de LibreOffice; App lo
    lanza, no lo importa) y `recursos/` (plantilla `main.ods` con su Module1). Comandos
    `sistema-ventas` y `sistema-ventas instalar`.
  - **Canal con UNO:** `multiprocessing.connection` (stdlib en los dos lados: socket de archivo en
    Linux, pipe con nombre en Windows), con clave de acceso y mensajes JSON `{tipo, datos}`.
  - **Acciones de los botones: híbrido modular.** Un archivo por acción en `acciones/`, que
    declara `ACCION = Accion(nombre, etiqueta, ejecutar)`. Al arrancar se descubren y validan;
    los errores van al log y admin_botones solo ofrece las válidas. Una prueba verifica que
    cada botón de la base apunte a una acción existente.

## 5. Pendientes abiertos (2026-10-03)

Lo que queda sin decidir o sin medir después de cerrar D1–D20. Los diagramas de
`diagramas/` lo marcan como supuesto o nota donde aplica.

**Por decidir**

1. ~~¿Quién es "el administrador" en la V3?~~ **Resuelto (2026-10-06): el usuario que instala,
   con el papel de "desarrollador"** (ver D21).
   `sistema-ventas instalar` lo marca como administrador en la tabla de usuarios de `ventas.db`
   (sustituye a `ADMIN_RAIZ` de la V2). Pendiente: cómo se transfiere o se agrega otro desde el
   menú de administración.
2. ~~camera_viewer abierto desde una ejecución anterior~~ **Resuelto (2026-10-06): ver D22.**
   - Idea del usuario: las cámaras corren en la misma App Qt, que no se cierra mientras las
     cámaras sigan abiertas. El acceso directo, si la App ya corre, le pide que vuelva a abrir
     LibreOffice y lo demás. Cuando se cierra lo último que quedaba, la App sí se cierra.
   - Ajuste propuesto: App como proceso de larga vida y dueña de todo (POS, LibreOffice,
     cámaras), pero **camera_viewer como proceso hijo de App** (aislado: OpenCV y el video son lo
     más frágil; un fallo no debe tumbar la caja), conectado por el mismo tipo de canal que UNO.
     App sabe siempre si está abierto, le pide saltar a una hora y le pasa las ventas.
   - Instancia única por usuario (D8) con aviso a la App ya abierta: patrón convencional de
     aplicación de escritorio.
   - **Logs:** una ejecución = la vida de App. Se sigue en el mismo archivo al reabrir
     LibreOffice, con una marca (`=== LibreOffice abierto de nuevo (sesión N) ===`). Solo se cambia
     de archivo al cambiar el día, con el enlace "continúa en / viene de" de D20.
   - Confirmado por el usuario: cámaras como proceso hijo de App. Falta coordinar con la
     instancia de cámaras el canal App ↔ camera_viewer.
3. ~~Código de apertura de caja: ¿uno solo o uno por usuario?~~ **Resuelto (2026-10-06): ver
   D21.** Contexto de la discusión:
   - Caso límite actual: si el código no está configurado (p. ej. se borró la configuración) y
     quien abre el sistema no es el administrador, no puede abrir la caja con código hasta que
     el administrador lo configure. Con el código pedido en la instalación, casi no ocurre.
   - Idea del usuario: cada usuario inventa su propio código la primera vez que abre la caja.
     Cambia el propósito: un código único **autoriza** (solo quien la dueña elija lo conoce); uno
     por usuario inventado libremente solo **identifica**, y el usuario ya está identificado por
     su sesión del SO (solo protege si otra persona usa una sesión ajena abierta).
   - Pregunta abierta para el usuario: ¿el código sirve para autorizar o para saber quién abrió?
     Para saber quién abrió, cada apertura ya puede guardar usuario y sesión.
   - Nota: la V2 guarda el código en texto plano en `autorizaciones_codigos` en cada apertura. En
     la V3 no se guarda el código, sino quién lo usó.

**Por medir o probar (con el prototipo)**

4. **D6. Foco:** que el diálogo de cobro Qt, abierto desde un Enter, aparezca al frente con el
   teclado activo, y que el foco vuelva a Calc y a B4 al cerrarlo.
5. **D13. Macros sin avisos:** que el perfil propio de LibreOffice con la carpeta de `main.ods`
   como ubicación de confianza deje correr las macros sin preguntar.
6. **D20. Versión mínima de LibreOffice:** probar versiones viejas descargadas del archivo
   oficial, extraídas aparte con perfil propio (UNO, teclado de D1, pintar tablas, macros).
7. **D1 en Windows y con el POS cargado:** repetir la medición del teclado con
   `pruebas/d1_teclado/escucha_teclado.py`.
8. **Instalador de uv en Linux:** el script oficial lo deja en la carpeta personal del
   administrador. Debería bastar, porque los usuarios usan `sistema-ventas` desde
   `UV_TOOL_BIN_DIR`; hay que confirmarlo al instalar.

**Supuestos de los diagramas que siguen en pie**

9. Enter se consume en UNO (a diferencia del Tab, D14).
10. Se conserva "¿venta en curso?" además del descarte de Enter de D17.
11. El ticket abre el cajón como en la V2 (`print_sale`); el cobro sin ticket lo abre con una
    tarea propia y sin evento APERTURA DE CAJA.

**Fuera de la V3, pero detectado aquí**

12. El código de apertura de caja de la V2 (`7410`, en `nucleo/config.py`) es público en el
    repositorio de GitHub. Conviene cambiarlo en la V2.
13. **Posibilidad, a revisar más adelante:** lector de códigos con distribución de teclado de
    EE. UU.: `SN:GLH…` llega como `SNÑGLH…` (D1). En la práctica casi no estorba: los códigos
    numéricos salen igual y el lector siempre traduce igual, así que el código se registra y se
    encuentra bien. Solo afectaría si se compara con texto tecleado a mano o si se imprime una
    etiqueta con ese código (Code 128 no admite la `Ñ`). Si hiciera falta: configurar el lector
    en español o traducir esos caracteres.

