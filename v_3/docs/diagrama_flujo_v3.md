# Diagrama de flujo de la V3: índice y documentación

Todos los diagramas están en [`diagramas/`](diagramas/), uno por archivo `.mmd` (Mermaid puro),
para revisarlos juntos en un visualizador. Los del flujo empiezan con `flujo_` y los de la
instalación con `instalacion_` (índice aparte: [`diagrama_instalacion_v3.md`](diagrama_instalacion_v3.md)).
Este archivo es el índice del flujo: cómo leerlo, qué hay en cada archivo, las tablas de pines,
la verificación de pareja de pines y las discrepancias.

Cada proceso de la V3 es un **chip** con pines de entrada y salida, como microcontroladores en
una placa. Fuentes: `mapa_v2.md` (D1–D22 y su sección 5, al 2026-10-06), `arranque_v3.md` y
`../README.md`.

## Cómo leerlo

Convenciones de ISO 5807 / ANSI X3.5, con las decisiones de forma del usuario:

| Símbolo | Forma en Mermaid | Significado | Regla |
|---|---|---|---|
| Terminal | Estadio `(["…"])` | Inicio o fin de una página, o un evento que no viene de un pin (un temporizador o una señal entre hilos) | Si es inicio, una salida; si es fin, ninguna. |
| Proceso | Rectángulo `["…"]` | Un paso | Exactamente **una** salida. |
| Proceso predefinido | Rectángulo con barras `[["…"]]` | Un subflujo dibujado en otro archivo del mismo chip | Exactamente una salida. |
| Datos | Paralelogramo `[/"…"/]` | Lectura de datos que no vienen de otro chip | Exactamente una salida. |
| Almacenamiento | Cilindro `[("…")]` | Lectura o escritura de un archivo o base (`ventas.db`, `main.ods`, perfil, `.evt`, log, candado) | Exactamente **una** entrada y **una** salida. |
| Decisión | Rombo `{"…"}` | Pregunta | El único que se bifurca; cada salida va etiquetada. |
| Conector de salida | Círculo `(("OUT …"))` | Pin hacia otro chip | Le llega **una** línea y el camino **termina** ahí. |
| Conector de entrada | Círculo `(("IN …"))` | Pin desde otro chip | Sale **una** línea y el camino **empieza** ahí. |
| Modo paralelo | Barra oscura «═══ en paralelo ═══» | Un paso dispara varias salidas o caminos a la vez | La única excepción a «una salida», siempre explícita. |

- **Nunca hay una flecha entre dos conectores.** Cuando un proceso manda algo y espera la
  respuesta, el camino termina en el OUT y el flujo sigue aparte, desde el IN de la respuesta.
  Si hay varios IN con el mismo nombre en un archivo, el paréntesis dice a qué espera responde
  cada uno (por ejemplo, «IN respuesta_usuario (cobro)»).
- **Enviar y seguir.** Cuando un proceso manda algo sin esperar respuesta y además sigue, o
  manda dos cosas a la vez, se usa la barra «en paralelo». También se usa para lanzar un hilo de
  trabajo (D18): una rama va al hilo y la otra sigue en el hilo principal.
- **Nacimiento y muerte de un hijo:** empieza en su IN `arrancar_*`, y su fin se ve en el OUT
  `*_salio`, que es el código de salida que recibe App.
- **Unión de líneas.** Varias líneas pueden llegar a un mismo proceso, rombo o terminal. A los
  conectores y cilindros les llega siempre una sola.
- **Colores** (ver `flujo_00_leyenda.mmd`):
  - Cada nodo lleva el color del proceso donde corre.
  - Las macros Basic son un actor dentro del chip de soffice y llevan su propio color.
  - Cada **OUT** lleva el color del chip **destino** y cada **IN** el del chip de **origen**.
    Son grises si el otro extremo no es un proceso (usuario, SO, impresoras, DVR).
  - Cada **cilindro** lleva el color del proceso que consigue esos datos. Por ejemplo,
    `ventas.db` va en el color de App (sqlite corre dentro de App), y el `.evt` que escribe
    Basic va en el de Basic.

## Archivos

| Archivo | Chip | Qué muestra |
|---|---|---|
| `flujo_00_leyenda.mmd` | — | Colores de cada proceso. |
| `flujo_01a_app_arranque.mmd` | App | Instancia única con aviso a la App ya abierta (D22), log de la ejecución, LibreOffice, migraciones, usuario y permisos, turno de caja (D8) y código de caja pendiente para quien tiene «abrir caja sin límite» (D21). |
| `flujo_01b_app_abrir_libreoffice.mmd` | App | Marca en el log al reabrir (D22), perfil propio (D13), copia de `main.ods` (D7), prebake (D4) y arranque de soffice. |
| `flujo_01c_app_conectar_uno.mmd` | App | Canal con UNO (D18), configuración `consumir_tab` (D14), botones y modo; reintentos. |
| `flujo_01d_app_eventos.mmd` | App | Lo que App atiende mientras vive: Enter, Tab (D14), botones, turno cada ~3 s, cierres, reabrir LibreOffice y camera_viewer como hijo (D22), y señales de los hilos de trabajo. |
| `flujo_01e_app_atender_enter.mmd` | App | ControladorVenta: descartes de D17, regla de escaneo (D10), código nuevo, agregar, cobrar o abrir la caja. |
| `flujo_01f_app_cobrar.mmd` | App | Cobro con ticket o sin ticket (D15). |
| `flujo_01g_app_atender_boton.mmd` | App | Cada botón de la hoja, incluidos el menú del desarrollador y el código de caja (D21). |
| `flujo_01h_app_menu_desarrollador.mmd` | App | Menú del desarrollador (D21): botones (D12), permisos por usuario y configuración. |
| `flujo_01i_app_abrir_camaras.mmd` | App | Abrir camera_viewer, o pedirle una fecha y hora o ponerse al frente si ya está abierto (D11, D22). |
| `flujo_01j_app_tras_salir_soffice.mmd` | App | Turno perdido, cambio de modo, cierre normal o caída; App sigue viva si camera_viewer está abierto (D22). |
| `flujo_01k_app_cierre.mmd` | App | Cierre de App, cuando ya no queda nada abierto (D22). |
| `flujo_01l_app_comprobar_turno.mmd` | App | Comprobación del turno de caja (D8). |
| `flujo_01m_app_abrir_caja.mmd` | App | Abrir la caja: permiso, ventana diaria de la empleada o código de un solo uso (D21). |
| `flujo_01n_app_hilos_de_trabajo.mmd` | App | Hilos de trabajo con tiempo máximo (D18), su señal en el hilo principal y el registro de cada apertura (D21). |
| `flujo_01o_app_log_y_vigilante.mmd` | App | Log de la ejecución, un archivo por día (D22), vigilante del bucle de Qt y tracebacks para IA (D18). |
| `flujo_01p_app_configurar_codigo_caja.mmd` | App | Configurar el código de autorización: lo hace un usuario con «abrir caja sin límite», viendo el uso anterior (D21). |
| `flujo_02_soffice_y_basic.mmd` | soffice | LibreOffice con `main.ods` y su actor Basic (D3 = a, D13, D20). |
| `flujo_03_uno.mmd` | UNO | Proceso UNO: pinta, captura teclas y sondea los `.evt`. |
| `flujo_04_camera_viewer.mmd` | camera_viewer | Hijo de App con su canal (D22); caja negra por dentro. |
| `flujo_99_placa.mmd` | — | Solo los bloques y los cables entre pines. |

**App es el proceso de larga vida y dueña de todo (D22).** Sus hijos son soffice, UNO y
camera_viewer; App no termina mientras alguno siga abierto. Si el acceso directo se usa con App
ya abierta, la App nueva le pide a la abierta que vuelva a abrir LibreOffice y termina.
admin_botones ya no es un proceso (D12), y el archivador de cámaras queda fuera de la V3.

## Supuestos que quedan

D2, D3, D4, D10, D18, D20, D21 y D22 ya están decididos y no se marcan como supuestos. Quedan:

- **Enter se consume** en UNO (`flujo_03_uno.mmd`, A5b). D14 solo fija el Tab.
- **De dónde sale la fecha y hora** para abrir las cámaras en una venta (`flujo_01i`).
- **Cómo llega a «su propio menú»** un usuario con «abrir caja sin límite» para cambiar el código
  (D21). Se dibujó como un botón CÓDIGO DE CAJA, visible solo para ellos (`flujo_01g`).
- **Cuándo recibe camera_viewer las ventas.** Se dibujó al conectarse (`ventas_del_dia`, en
  `flujo_01d`). Que reciba también cada venta nueva está por definir con la instancia de cámaras.
- **Mecanismo de `reabrir_libreoffice`:** un canal de instancia única en la carpeta de ejecución
  del usuario, del mismo tipo que el de UNO.

## Pines por chip

### App

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `inicio` | IN | Argumentos del entry point | SO | Creación de proceso (menú del sistema o menú Inicio) |
| `reabrir_libreoffice` | OUT | Pedido de volver a abrir LibreOffice | La App ya abierta del mismo usuario | Canal de instancia única (supuesto: `multiprocessing.connection` en la carpeta de ejecución) |
| `reabrir_libreoffice` | IN | Ídem | Una App nueva del mismo usuario | Ídem |
| `ventana_qt` | OUT | Diálogo, selector, aviso o ventana | Usuario | Qt |
| `respuesta_usuario` | IN | Lo que eligió, escribió o canceló | Usuario | Qt |
| `arrancar_soffice` | OUT | Perfil propio, `--accept=pipe,name=…`, `--norestore`, ruta | soffice | Creación de proceso |
| `terminar_soffice` | OUT | Terminar el proceso | soffice | `terminate()` del hijo (solo si UNO no arranca) |
| `soffice_salio` | IN | Código de salida | soffice | Espera del proceso hijo |
| `log_soffice` | IN | stdout/stderr | soffice | Tubería |
| `arrancar_uno` | OUT | Pipe de soffice, dirección y clave del canal | UNO | Creación de proceso |
| `configurar` | OUT | `consumir_tab` (D14) | UNO | `multiprocessing.connection` (D18) |
| `uno_listo` | IN | Conectado y handlers registrados | UNO | Ídem |
| `enter_pulsado` | IN | Fila de entrada, texto del tramo y horas de llegada (D10) | UNO | Ídem |
| `tab_pulsado` | IN | Texto de B4 | UNO | Ídem |
| `boton_pulsado` | IN | id del botón | UNO | Ídem |
| `documento_cerrado` | IN | Motivo: cierre normal o caída | UNO | Ídem |
| `uno_salio` | IN | Código de salida | UNO | Espera del proceso hijo |
| `log_uno` | IN | stdout/stderr | UNO | Tubería |
| `pintar` | OUT | Modo (`normal` o `ventas_dia` con fecha); filas; fila de evento | UNO | `multiprocessing.connection` |
| `escribir_producto` | OUT | Producto para B4 | UNO | Ídem |
| `publicar_botones` | OUT | Lista (id, etiqueta) | UNO | Ídem |
| `enfocar_calc` | OUT | Foco a Calc, en B4 o sin mover el cursor | UNO | Ídem |
| `cerrar_libreoffice` | OUT | Orden de cierre | UNO | Ídem |
| `arrancar_camaras` | OUT | Dirección y clave del canal y, opcionalmente, fecha y hora | camera_viewer | Creación de proceso (D22) |
| `camaras_lista` | IN | Conectado al canal | camera_viewer | `multiprocessing.connection` (D22) |
| `ventas_del_dia` | OUT | Horas de las ventas del día | camera_viewer | Ídem |
| `abrir_en_fecha_hora` | OUT | Fecha y hora | camera_viewer | Ídem |
| `mostrar_camaras` | OUT | Ponerse al frente | camera_viewer | Ídem |
| `log_camaras` | IN | Líneas de log | camera_viewer | Ídem (D22) |
| `camaras_salio` | IN | Código de salida | camera_viewer | Espera del proceso hijo |
| `imprimir_ticket` | OUT | Ticket con apertura del cajón | Impresora de tickets | Driver, en un hilo de trabajo (D18) |
| `ticket_resultado` | IN | ¿Se imprimió? | Impresora de tickets | Resultado de la llamada |
| `abrir_cajon` | OUT | Pulso de apertura | Impresora de tickets (cajón) | Driver, en un hilo de trabajo |
| `cajon_resultado` | IN | ¿Se abrió? | Impresora de tickets | Resultado de la llamada |
| `imprimir_etiqueta` | OUT | Imagen del código | Impresora de etiquetas | Driver, en un hilo de trabajo |
| `etiqueta_resultado` | IN | ¿Se imprimió? | Impresora de etiquetas | Resultado de la llamada |

Almacenamiento de App (cilindros, no pines):

| Archivo | Uso | Dónde vive |
|---|---|---|
| `ventas.db` | Ventas, usuarios y **permisos** (D21), sesiones, catálogo, códigos, botones, eventos, **turno de caja** (D8), **hash y estado del código de autorización** (D20, D21) y cada **apertura de caja** con quién y cómo se autorizó (D21) | Carpeta de datos compartida (grupo, D19) |
| Candado del usuario | Instancia única por usuario (D8) | Carpeta de ejecución del usuario; lo suelta el SO |
| Perfil de LibreOffice del usuario | Ubicación de confianza para las macros (D13) | Carpeta de datos del usuario |
| `main.ods` del usuario | Copia de la plantilla, horneada (D4, D7) | Carpeta del usuario |
| Log de la ejecución | Un archivo por día, con marcas al reabrir LibreOffice y «continúa en / viene de» (D22) | Carpeta de logs |

### soffice (con Basic)

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `arrancar_soffice` | IN | Argumentos | App | Creación de proceso |
| `terminar_soffice` | IN | Orden de terminar | App | `terminate()` del SO |
| `teclado_raton` | IN | Teclas (también las del escáner) y clics | Usuario | Sistema de ventanas |
| `urp_conectar` | IN | Pedido de conexión | UNO | URP por el pipe con nombre |
| `api_hoja` | IN | Llamada a la API | UNO | URP |
| `tecla_respuesta` | IN | ¿Consumida? | UNO | Retorno de `XKeyHandler.keyPressed` |
| `invocar_macro` | IN | Macro Basic y argumentos: preparar (con la **ruta de la carpeta de ejecución del usuario**, D20), limpiar, crear botón | UNO | Script provider por URP (como `SheetButtonBridge`) |
| `log_soffice` | OUT | stdout/stderr | App | Tubería |
| `pantalla_hoja` | OUT | La hoja | Usuario | Ventana de LibreOffice |
| `urp_listo` | OUT | Conexión aceptada | UNO | URP |
| `api_respuesta` | OUT | Resultado de la llamada o de la macro | UNO | URP |
| `tecla` | OUT | `KeyEvent` | UNO | Callback `XKeyHandler.keyPressed` |
| `documento_murio` | OUT | El documento dejó de existir | UNO | Excepción en la siguiente llamada |
| `soffice_salio` | OUT | Código de salida | App | Fin del proceso hijo |

Almacenamiento: soffice lee el `main.ods` del usuario; Basic escribe un `.evt` por clic en la
carpeta que le pasó UNO (D3, D20).

### UNO

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `arrancar_uno` | IN | Pipe de soffice, dirección y clave | App | Argumentos del proceso |
| `configurar` | IN | `consumir_tab` | App | `multiprocessing.connection` |
| `pintar` | IN | Modo y filas | App | Ídem |
| `escribir_producto` | IN | Producto | App | Ídem |
| `enfocar_calc` | IN | Foco | App | Ídem |
| `publicar_botones` | IN | Lista (id, etiqueta) | App | Ídem |
| `cerrar_libreoffice` | IN | Orden | App | Ídem |
| `urp_listo` | IN | Conexión aceptada | soffice | URP |
| `api_respuesta` | IN | Resultado de la llamada | soffice | URP |
| `tecla` | IN | `KeyEvent` | soffice | Callback `XKeyHandler` |
| `documento_murio` | IN | El documento dejó de existir | soffice | Excepción en la llamada |
| `urp_conectar` | OUT | Pedido de conexión | soffice | URP |
| `api_hoja` | OUT | Llamada a la API | soffice | URP |
| `tecla_respuesta` | OUT | ¿Consumida? | soffice | Retorno de `keyPressed` |
| `invocar_macro` | OUT | Macro Basic y argumentos, incluida la ruta de la carpeta de ejecución (D20) | soffice (Basic) | Script provider |
| `uno_listo` | OUT | Conectado y handlers registrados | App | `multiprocessing.connection` |
| `enter_pulsado` | OUT | Fila, texto y horas de llegada | App | Ídem |
| `tab_pulsado` | OUT | Texto de B4 | App | Ídem |
| `boton_pulsado` | OUT | id | App | Ídem |
| `documento_cerrado` | OUT | Motivo | App | Ídem |
| `uno_salio` | OUT | Código de salida | App | Fin del proceso hijo |
| `log_uno` | OUT | stdout/stderr, tracebacks en texto plano | App | Tubería |

Almacenamiento: UNO lee y borra los `.evt` de la carpeta de ejecución del usuario cada 0.5 s
(D3).

### camera_viewer (hijo de App, caja negra por dentro)

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `arrancar_camaras` | IN | Dirección y clave del canal; fecha y hora opcional | App | Creación de proceso |
| `ventas_del_dia` | IN | Horas de las ventas del día | App | `multiprocessing.connection` (D22) |
| `abrir_en_fecha_hora` | IN | Fecha y hora | App | Ídem |
| `mostrar_camaras` | IN | Ponerse al frente | App | Ídem |
| `respuesta_camaras` | IN | Interacción del usuario | Usuario | Qt |
| `dvr_camaras_datos` | IN | Video | DVR | Propio de la caja negra |
| `camaras_lista` | OUT | Conectado al canal | App | `multiprocessing.connection` |
| `log_camaras` | OUT | Líneas de log | App | Ídem (D22) |
| `ventana_camaras` | OUT | Ventana | Usuario | Qt |
| `dvr_camaras_pedir` | OUT | Pedidos al DVR | DVR | Propio de la caja negra |
| `camaras_salio` | OUT | Código de salida | App | Fin del proceso hijo |

Almacenamiento: ya no lee `ventas.db` ni `log_actual`. App le pasa las ventas y su log va por el
canal (D22).

## Verificación de pines

Cada cable, con su OUT y su IN. Los extremos grises no son procesos, pero se cuentan para que
ningún pin quede suelto.

| # | Pin | De (OUT) | A (IN) | Mecanismo |
|---|---|---|---|---|
| 1 | `inicio` | SO | App | Creación de proceso |
| 2 | `reabrir_libreoffice` | App nueva del mismo usuario | App ya abierta | Canal de instancia única |
| 3 | `ventana_qt` | App | Usuario | Qt |
| 4 | `respuesta_usuario` | Usuario | App | Qt |
| 5 | `imprimir_ticket` | App | Impresora de tickets | Driver |
| 6 | `ticket_resultado` | Impresora de tickets | App | Resultado de la llamada |
| 7 | `abrir_cajon` | App | Impresora de tickets | Driver |
| 8 | `cajon_resultado` | Impresora de tickets | App | Resultado de la llamada |
| 9 | `imprimir_etiqueta` | App | Impresora de etiquetas | Driver |
| 10 | `etiqueta_resultado` | Impresora de etiquetas | App | Resultado de la llamada |
| 11 | `arrancar_soffice` | App | soffice | Creación de proceso |
| 12 | `terminar_soffice` | App | soffice | `terminate()` |
| 13 | `soffice_salio` | soffice | App | Fin de proceso |
| 14 | `log_soffice` | soffice | App | Tubería |
| 15 | `arrancar_uno` | App | UNO | Creación de proceso |
| 16 | `configurar` | App | UNO | Canal |
| 17 | `pintar` | App | UNO | Canal |
| 18 | `escribir_producto` | App | UNO | Canal |
| 19 | `publicar_botones` | App | UNO | Canal |
| 20 | `enfocar_calc` | App | UNO | Canal |
| 21 | `cerrar_libreoffice` | App | UNO | Canal |
| 22 | `uno_listo` | UNO | App | Canal |
| 23 | `enter_pulsado` | UNO | App | Canal |
| 24 | `tab_pulsado` | UNO | App | Canal |
| 25 | `boton_pulsado` | UNO | App | Canal |
| 26 | `documento_cerrado` | UNO | App | Canal |
| 27 | `uno_salio` | UNO | App | Fin de proceso |
| 28 | `log_uno` | UNO | App | Tubería |
| 29 | `urp_conectar` | UNO | soffice | URP |
| 30 | `urp_listo` | soffice | UNO | URP |
| 31 | `api_hoja` | UNO | soffice | URP |
| 32 | `api_respuesta` | soffice | UNO | URP |
| 33 | `tecla` | soffice | UNO | Callback URP |
| 34 | `tecla_respuesta` | UNO | soffice | Retorno del callback |
| 35 | `invocar_macro` | UNO | soffice (Basic) | Script provider |
| 36 | `documento_murio` | soffice | UNO | Excepción en la llamada |
| 37 | `teclado_raton` | Usuario | soffice | Sistema de ventanas |
| 38 | `pantalla_hoja` | soffice | Usuario | Pantalla |
| 39 | `arrancar_camaras` | App | camera_viewer | Creación de proceso |
| 40 | `camaras_lista` | camera_viewer | App | Canal |
| 41 | `ventas_del_dia` | App | camera_viewer | Canal |
| 42 | `abrir_en_fecha_hora` | App | camera_viewer | Canal |
| 43 | `mostrar_camaras` | App | camera_viewer | Canal |
| 44 | `log_camaras` | camera_viewer | App | Canal |
| 45 | `camaras_salio` | camera_viewer | App | Fin de proceso |
| 46 | `ventana_camaras` | camera_viewer | Usuario | Qt |
| 47 | `respuesta_camaras` | Usuario | camera_viewer | Qt |
| 48 | `dvr_camaras_pedir` | camera_viewer | DVR | Caja negra |
| 49 | `dvr_camaras_datos` | DVR | camera_viewer | Caja negra |

**Resultado:** los 49 cables tienen su OUT y su IN. Puntos sueltos deliberados:

- **El código de salida de App no tiene pin**: nadie lo lee.
- **No hay pin para matar a UNO.** Si no arranca, App termina soffice y UNO sale al recibir
  `documento_murio` (`flujo_01c`).
- **No hay pin hacia la App desplazada por otro usuario** (D20). Se entera en su siguiente
  comprobación del turno, cada ~3 s (`flujo_01d`). El único pin entre instancias es
  `reabrir_libreoffice`, entre dos Apps del **mismo** usuario (D22).
- **Los clics de Basic llegan a UNO por archivo** (`.evt`, cilindros en `flujo_02` y
  `flujo_03`), no por pin.

## Discrepancias encontradas

D21 y D22 resolvieron las tres primeras de la ronda anterior:
- Quién es el administrador: el desarrollador.
- camera_viewer ya abierto: ahora es hijo de App.
- Caja con código sin administrador: el código lo configura quien tiene «abrir caja sin límite».

Quedan:

1. **Doble comprobación de «venta en curso».** `flujo_01e` conserva el rombo «¿Hay una venta en
   curso?» además de los dos descartes de D17 (sección 5 del mapa, punto 10).
2. **El ticket también abre el cajón** (sección 5, punto 11). Por eso el cobro sin ticket abre el
   cajón con una tarea propia, sin evento APERTURA DE CAJA (`flujo_01f`, `flujo_01n`). D21 pide
   registrar «cada apertura» con cómo se autorizó. Las aperturas por venta, con o sin ticket,
   quedan registradas como venta, no como apertura. Si se quieren también en el registro de
   aperturas, habría que agregarlas (autorizada por: venta).
3. **Enter con el carrito vacío.** En la V2 pedía el código y abría la caja. Aquí lleva a la misma
   página que el botón ABRIR CAJA (`flujo_01m`), así que también aplican el permiso y la
   ventana diaria de D21. El mapa no lo dice expresamente.
4. **Usuario sin ningún permiso de caja.** D21 define «abrir caja sin límite» y «empleada».
   Un usuario sin ninguno de los dos va directo al código de autorización (`flujo_01m`, rombo
   «¿Tiene el permiso «empleada»?»). Falta confirmar que ese es el comportamiento querido.
5. **Reabrir LibreOffice con el turno perdido.** Si a una App la desplazó otro usuario, pero
   camera_viewer sigue abierto, App sigue viva (D22). Si el mismo usuario vuelve a usar el
   acceso directo, `flujo_01d` vuelve a tomar el turno antes de abrir LibreOffice, como un
   arranque nuevo (D8: el último que abre se queda con la caja). El mapa no trata este caso
   combinado.

## Cómo se verificó

Con `verificar_iso.py` (Python, solo biblioteca estándar), sobre los archivos `flujo_*.mmd` de
`diagramas/` y este índice:

- Cada `.mmd` es Mermaid puro, sin marcas de bloque, y empieza con `%% chip: X`, `%% placa` o
  `%% leyenda` seguida de un comentario.
- Cada archivo del conjunto aparece en este índice, cada archivo que nombra el índice existe, y
  cada referencia a una página (`[["… (1x)"]]`) apunta a una página que existe.
- En cada chip:
  - Rectángulos, predefinidos y paralelogramos tienen exactamente una salida, sin etiqueta, y al
    menos una entrada.
  - Cada conector tiene una sola línea: un OUT recibe una y no sale ninguna, y un IN no recibe
    ninguna y sale una. Ninguna arista va de un conector a otro.
  - Cada cilindro tiene exactamente una entrada y una salida.
  - Los rombos tienen dos o más salidas, todas etiquetadas. Solo las barras «en paralelo» se
    bifurcan sin rombo.
  - Los terminales son de inicio o de fin.
  - Cada OUT lleva el color del destino y cada IN el del origen, gris si no es un proceso. Los
    demás nodos llevan el color de su chip; en soffice, también el de Basic.
- En todo el código: ninguna flecha doble ni hexágono.
- Cada OUT tiene su IN con el mismo nombre en otro chip o en un extremo gris de la placa, y al
  revés. La excepción es `reabrir_libreoffice`, que une dos instancias de App. Todos los pines
  aparecen en la placa y en la tabla de verificación.
