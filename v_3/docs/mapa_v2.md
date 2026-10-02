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

- **D2. Dónde vive la lógica de negocio.** La propuesta pone controlador, carrito, servicios y
  acciones en App, y deja a UNO solo pintando y preguntando. La alternativa es dejar más lógica
  en UNO (`sqlite3` es stdlib): menos mensajes, pero la base con dos dueños y la regla "UNO sin
  paquetes" más difícil de sostener.
- **D3. Clics en botones.** Hoy: Basic → un `.evt` por clic → Python sondea cada 0.5 s. Opciones:
  - (a) Conservarlo.
  - (b) Registrar desde Python un `XActionListener` en cada botón. Así sobran el spool, el
    sondeo y buena parte de Module1.
- **D4. Prebake.** ¿Sigue teniendo sentido hornear `main.ods` con odfpy antes de abrir, o App le
  pasa las filas a UNO y este pinta al arrancar? Depende de cuánto tarde pintar en vivo; el
  prebake existe por eso.
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
- **D7. `main.ods` por usuario — a favor, con una condición del usuario.** Ningún usuario puede
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
    dejó abierta. Cambio respecto a la V2: el que llega le **pide** a la instancia anterior que
    se cierre en orden (registra su sesión como cerrada y por quién), por un punto de encuentro
    en la carpeta de datos compartida, sin root ni `kill`.
  - **Si la App anterior no responde** (colgada): la espera tiene un tiempo máximo (~10 s) y
    luego la nueva toma la caja de todos modos. Sin root no puede matar un proceso de otro
    usuario, así que la protección es una **ficha de caja con número de turno** (fencing token)
    en la carpeta compartida. Tomar la caja sube el número. Antes de cada acción con efecto (vender,
    imprimir, abrir el cajón, escribir en la base), una App comprueba que su número sigue siendo
    el vigente; si no, no hace nada, avisa y se cierra. Así, si la colgada revive, ya no puede
    tocar nada.
  - Pendiente de confirmar con el usuario: qué pasa con un carrito a medias en la sesión que se
    cierra (la V2 lo pierde).
- **D9. Sin rutas fijas.** Ni `/home/jesjack/...` ni `C:\Users\jesjack\...` en ningún archivo.
  - Las rutas del programa se derivan de dónde está instalado.
  - Las de datos, de las rutas estándar de cada sistema (`platformdirs`).
  - LibreOffice se busca en el PATH (Linux) o en el registro (Windows).
  - Así el prebake y soffice nunca pueden usar archivos distintos, como hoy en `open_system.sh`.
- **D10. ¿Quién decide si fue escaneo?** La regla de D1 necesita las horas de llegada, que se
  toman en UNO. Opciones:
  - (a) UNO aplica la regla y manda el veredicto. Es lo que dibujó `diagrama_flujo_v3.md`.
  - (b) UNO manda las horas crudas y App decide.

  Recomendación: (b). UNO se queda sin reglas de negocio, como el resto de su papel (pintar y
  capturar). Los umbrales viven y se ajustan en un solo lugar, junto a su registro en el log, y
  se pueden probar sin LibreOffice. El costo es mandar unas pocas horas extra por cada Enter.
- **D11. ¿camera_viewer se cierra con el POS?** En la V2 sobrevive al cierre (`atexit` solo
  detiene al archivador). Pendiente del usuario, y de la otra instancia, que lleva las cámaras.
- **D12. admin_botones: ¿hijo aparte o ventana de App?** Propuesta de `diagrama_flujo_v3.md`:
  ventana de App. El proceso aparte existía porque `main.py` no tenía Qt y corría como root.
  Como ventana, hay un solo dueño de `ventas.db` y desaparece el sondeo de `revisar_cambios`.
  Costo: un fallo en esa ventana ya no queda aislado del POS.

