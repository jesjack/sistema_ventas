# Diagrama de flujo de la V3: índice y documentación

Todos los diagramas están en [`diagramas/`](diagramas/), uno por archivo `.mmd` (Mermaid puro),
para revisarlos juntos en un visualizador. Los del flujo empiezan con `flujo_` y los de la
instalación con `instalacion_` (índice aparte: [`diagrama_instalacion_v3.md`](diagrama_instalacion_v3.md)).
Este archivo es el índice del flujo: cómo leerlo, qué hay en cada archivo, las tablas de pines,
la verificación de pareja de pines y las discrepancias.

Cada proceso de la V3 es un **chip** con pines de entrada y salida, como microcontroladores en
una placa. Fuentes: `mapa_v2.md` (D1–D20, al 2026-10-03), `arranque_v3.md` y `../README.md`.

## Cómo leerlo

Convenciones de ISO 5807 / ANSI X3.5, con las decisiones de forma del usuario:

| Símbolo | Forma en Mermaid | Significado | Regla |
|---|---|---|---|
| Terminal | Estadio `(["…"])` | Inicio o fin de una página, o un evento que no viene de un pin (un temporizador o una señal entre hilos) | Si es inicio, una salida; si es fin, ninguna. |
| Proceso | Rectángulo `["…"]` | Un paso | Exactamente **una** salida. |
| Proceso predefinido | Rectángulo con barras `[["…"]]` | Un subflujo dibujado en otro archivo del mismo chip | Exactamente una salida. |
| Datos | Paralelogramo `[/"…"/]` | Lectura de datos que no vienen de otro chip | Exactamente una salida. |
| Almacenamiento | Cilindro `[("…")]` | Lectura o escritura de un archivo o base (`ventas.db`, `main.ods`, perfil, `.evt`, log, `log_actual`, candado) | Exactamente **una** entrada y **una** salida. |
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
    `ventas.db` va en el color de App (sqlite corre dentro de App); en camera_viewer va en el de
    camera_viewer, que la lee por su cuenta; y el `.evt` que escribe Basic va en el de Basic.

## Archivos

| Archivo | Chip | Qué muestra |
|---|---|---|
| `flujo_00_leyenda.mmd` | — | Colores de cada proceso. |
| `flujo_01a_app_arranque.mmd` | App | `log_actual` (D20), candado del usuario, búsqueda de LibreOffice, migraciones, registro de usuario, toma del turno de caja (D8) y código de caja (D20). |
| `flujo_01b_app_abrir_libreoffice.mmd` | App | Perfil propio (D13), copia de `main.ods` (D7), prebake (D4) y arranque de soffice. |
| `flujo_01c_app_conectar_uno.mmd` | App | Canal con UNO (D18), configuración `consumir_tab` (D14), botones y modo; reintentos. |
| `flujo_01d_app_eventos.mmd` | App | Lo que App atiende mientras está abierta: Enter, Tab (D14), botones, turno cada ~3 s (D20), cierres y señales de los hilos de trabajo. |
| `flujo_01e_app_atender_enter.mmd` | App | ControladorVenta: descartes de D17, regla de escaneo (D10), código nuevo, agregar, cobrar o abrir la caja con el código (hash, D20). |
| `flujo_01f_app_cobrar.mmd` | App | Cobro con ticket o sin ticket (D15). |
| `flujo_01g_app_atender_boton.mmd` | App | Cada botón de la hoja. |
| `flujo_01h_app_menu_administracion.mmd` | App | Menú de administración, solo para el administrador: botones (D12) y código de caja (D20). |
| `flujo_01i_app_abrir_camaras.mmd` | App | Abrir camera_viewer, con o sin fecha y hora (D11). |
| `flujo_01j_app_tras_salir_soffice.mmd` | App | Turno perdido, cambio de modo, cierre normal o caída. |
| `flujo_01k_app_cierre.mmd` | App | Cierre de App. |
| `flujo_01l_app_comprobar_turno.mmd` | App | Comprobación del turno de caja (D8). |
| `flujo_01m_app_abrir_caja.mmd` | App | Abrir el cajón (botón y código autorizado). |
| `flujo_01n_app_hilos_de_trabajo.mmd` | App | Hilos de trabajo con tiempo máximo (D18) y su señal en el hilo principal. |
| `flujo_01o_app_log_y_vigilante.mmd` | App | Log único, vigilante del bucle de Qt y tracebacks para IA (D18). |
| `flujo_01p_app_configurar_codigo_caja.mmd` | App | Configurar el código de apertura de caja, guardado como hash (D20). |
| `flujo_02_soffice_y_basic.mmd` | soffice | LibreOffice con `main.ods` y su actor Basic (D3 = a, D13, D20). |
| `flujo_03_uno.mmd` | UNO | Proceso UNO: pinta, captura teclas y sondea los `.evt`. |
| `flujo_04_camera_viewer.mmd` | camera_viewer | Caja negra (otra instancia): pines de D11 y log que sigue a `log_actual` (D20). |
| `flujo_99_placa.mmd` | — | Solo los bloques y los cables entre pines. |

**Hijos de App:**
- soffice y UNO: App los lanza y los vigila.
- camera_viewer: App lo lanza, pero no se cierra con el POS (D11).

admin_botones ya no es un proceso (D12), y el archivador de cámaras queda fuera de la V3.

## Supuestos que quedan

D2, D3, D4, D10, D18 y D20 ya están decididos y no se marcan como supuestos. Quedan:

- **Enter se consume** en UNO (`flujo_03_uno.mmd`, A5b). D14 solo fija el Tab; si el Enter no
  se consume, Calc mueve el cursor y App lo devuelve con `enfocar_calc`, como en la V2.
- **De dónde sale la fecha y hora** para abrir las cámaras en una venta (`flujo_01i`). D11 pide
  la función, pero no dice qué parte de la interfaz elige la venta.
- **Quién es «el administrador».** En la V2 es la constante `ADMIN_RAIZ` (un nombre de usuario).
  La V3 lo necesita para el menú de administración (`flujo_01g`, `flujo_01h`) y para el aviso de
  código de caja al arrancar (`flujo_01a`). El mapa no dice cómo se define en la V3.

## Pines por chip

### App

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `inicio` | IN | Argumentos del entry point | SO | Creación de proceso (menú del sistema o menú Inicio) |
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
| `arrancar_camaras` | OUT | Módulo y, opcionalmente, fecha y hora | camera_viewer | Creación de proceso |
| `abrir_en_fecha_hora` | OUT | Fecha y hora | camera_viewer | Por definir con la instancia de cámaras (D11) |
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
| `ventas.db` | Ventas, usuarios, sesiones, catálogo, códigos, botones, eventos, **turno de caja** (D8) y **hash del código de caja** (D20) | Carpeta de datos compartida (grupo, D19) |
| `log_actual` | Ruta del log de esta ejecución, para camera_viewer (D20) | Carpeta de ejecución del usuario |
| Candado del usuario | Instancia única por usuario (D8) | Carpeta de ejecución del usuario; lo suelta el SO |
| Perfil de LibreOffice del usuario | Ubicación de confianza para las macros (D13) | Carpeta de datos del usuario |
| `main.ods` del usuario | Copia de la plantilla, horneada (D4, D7) | Carpeta del usuario |
| Archivo de log de la ejecución | Log único (D18) | Carpeta de logs |

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

### camera_viewer (caja negra)

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `arrancar_camaras` | IN | Módulo y, opcionalmente, fecha y hora | App | Creación de proceso |
| `abrir_en_fecha_hora` | IN | Fecha y hora | App | Por definir (D11) |
| `respuesta_camaras` | IN | Interacción del usuario | Usuario | Qt |
| `dvr_camaras_datos` | IN | Video | DVR | Propio de la caja negra |
| `ventana_camaras` | OUT | Ventana | Usuario | Qt |
| `dvr_camaras_pedir` | OUT | Pedidos al DVR | DVR | Propio de la caja negra |
| `camaras_salio` | OUT | Código de salida | App | Fin del proceso |

Almacenamiento (todo en el color de camera_viewer):
- Lee `ventas.db`, solo lectura, para marcar las ventas en su línea de tiempo (D11).
- Lee `log_actual` antes de escribir cada línea y escribe en el log vigente. Si la ruta cambió,
  deja «continúa en …» en el viejo y «viene de …» en el nuevo (D20). Por eso ya no hay pin
  `log_camaras`: su log no pasa por App.

## Verificación de pines

Cada cable, con su OUT y su IN. Los extremos grises no son procesos, pero se cuentan para que
ningún pin quede suelto.

| # | Pin | De (OUT) | A (IN) | Mecanismo |
|---|---|---|---|---|
| 1 | `inicio` | SO | App | Creación de proceso |
| 2 | `ventana_qt` | App | Usuario | Qt |
| 3 | `respuesta_usuario` | Usuario | App | Qt |
| 4 | `imprimir_ticket` | App | Impresora de tickets | Driver |
| 5 | `ticket_resultado` | Impresora de tickets | App | Resultado de la llamada |
| 6 | `abrir_cajon` | App | Impresora de tickets | Driver |
| 7 | `cajon_resultado` | Impresora de tickets | App | Resultado de la llamada |
| 8 | `imprimir_etiqueta` | App | Impresora de etiquetas | Driver |
| 9 | `etiqueta_resultado` | Impresora de etiquetas | App | Resultado de la llamada |
| 10 | `arrancar_soffice` | App | soffice | Creación de proceso |
| 11 | `terminar_soffice` | App | soffice | `terminate()` |
| 12 | `soffice_salio` | soffice | App | Fin de proceso |
| 13 | `log_soffice` | soffice | App | Tubería |
| 14 | `arrancar_uno` | App | UNO | Creación de proceso |
| 15 | `configurar` | App | UNO | Canal |
| 16 | `pintar` | App | UNO | Canal |
| 17 | `escribir_producto` | App | UNO | Canal |
| 18 | `publicar_botones` | App | UNO | Canal |
| 19 | `enfocar_calc` | App | UNO | Canal |
| 20 | `cerrar_libreoffice` | App | UNO | Canal |
| 21 | `uno_listo` | UNO | App | Canal |
| 22 | `enter_pulsado` | UNO | App | Canal |
| 23 | `tab_pulsado` | UNO | App | Canal |
| 24 | `boton_pulsado` | UNO | App | Canal |
| 25 | `documento_cerrado` | UNO | App | Canal |
| 26 | `uno_salio` | UNO | App | Fin de proceso |
| 27 | `log_uno` | UNO | App | Tubería |
| 28 | `urp_conectar` | UNO | soffice | URP |
| 29 | `urp_listo` | soffice | UNO | URP |
| 30 | `api_hoja` | UNO | soffice | URP |
| 31 | `api_respuesta` | soffice | UNO | URP |
| 32 | `tecla` | soffice | UNO | Callback URP |
| 33 | `tecla_respuesta` | UNO | soffice | Retorno del callback |
| 34 | `invocar_macro` | UNO | soffice (Basic) | Script provider |
| 35 | `documento_murio` | soffice | UNO | Excepción en la llamada |
| 36 | `teclado_raton` | Usuario | soffice | Sistema de ventanas |
| 37 | `pantalla_hoja` | soffice | Usuario | Pantalla |
| 38 | `arrancar_camaras` | App | camera_viewer | Creación de proceso |
| 39 | `abrir_en_fecha_hora` | App | camera_viewer | Por definir (D11) |
| 40 | `camaras_salio` | camera_viewer | App | Fin de proceso |
| 41 | `ventana_camaras` | camera_viewer | Usuario | Qt |
| 42 | `respuesta_camaras` | Usuario | camera_viewer | Qt |
| 43 | `dvr_camaras_pedir` | camera_viewer | DVR | Caja negra |
| 44 | `dvr_camaras_datos` | DVR | camera_viewer | Caja negra |

**Resultado:** los 44 cables tienen su OUT y su IN. Puntos sueltos deliberados:

- **El código de salida de App no tiene pin**: nadie lo lee.
- **No hay pin para cerrar camera_viewer**: no se cierra con el POS (D11).
- **No hay pin para matar a UNO.** Si no arranca, App termina soffice y UNO sale al recibir
  `documento_murio` (`flujo_01c`).
- **No hay pin entre dos instancias de App** (D20). La App desplazada se entera en su siguiente
  comprobación del turno, cada ~3 s (`flujo_01d`), o antes de su siguiente acción con efecto.
- **Algunos datos se pasan por archivo, no por pin:**
  - Los clics de Basic llegan a UNO por `.evt` (cilindros en `flujo_02` y `flujo_03`).
  - camera_viewer sabe a qué log escribir por `log_actual` (cilindros en `flujo_01a` y
    `flujo_04`).

## Discrepancias encontradas

Las discrepancias 1 a 3 de la ronda anterior quedaron resueltas por D20:
- El aviso a la App desplazada es la comprobación cada ~3 s.
- UNO le pasa a Basic la ruta de la carpeta de ejecución.
- El log de camera_viewer sigue a `log_actual`.

Quedan:

1. **camera_viewer ya abierto (resto de la anterior 3).** Si camera_viewer quedó abierto de una
   ejecución anterior, la App actual no es su padre: no recibe su `camaras_salio` ni tiene vía
   para mandarle `abrir_en_fecha_hora` o saber si está abierto (`flujo_01i`). Pendiente con la
   instancia de cámaras, como pide D20.
2. **Doble comprobación de «venta en curso».** `flujo_01e` conserva el rombo «¿Hay una venta en
   curso?» además de los dos descartes de D17. Así se cubre el momento entre que se cierra el
   diálogo de cobro y `selling = no`. Si sobra, se quita.
3. **El ticket también abre el cajón.** En la V2, `print_sale` agrega la orden de abrir el cajón
   al imprimir. Aquí se conservó (`flujo_01f`, `flujo_01n`). Por eso «sin ticket» (D15) abre el
   cajón con una tarea propia, sin registrar el evento APERTURA DE CAJA: la venta ya queda
   registrada.
4. **Caja con código bloqueada sin administrador.** Si al arrancar no hay código de caja y el
   usuario no es el administrador, `flujo_01a` solo avisa: la apertura con código queda
   bloqueada (`flujo_01e`) hasta que el administrador lo configure. D20 dice «si falta, en la
   primera ejecución», sin precisar qué pasa si esa primera ejecución es de una empleada. Como
   `sistema-ventas instalar` ya pide el código, este caso solo debería pasar si se borró la
   configuración.

## Cómo se verificó

Con `verificar_iso.py` (Python, solo biblioteca estándar), sobre los archivos `flujo_*.mmd` de
`diagramas/` y este índice:

- Cada `.mmd` es Mermaid puro, sin marcas de bloque, y empieza con `%% chip: X`, `%% placa` o
  `%% leyenda` seguida de un comentario.
- Cada archivo del conjunto aparece en este índice, y cada archivo que nombra el índice existe.
- En cada chip:
  - Rectángulos, predefinidos y paralelogramos tienen exactamente una salida, sin etiqueta.
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
  revés. Todos los pines aparecen en la placa y en la tabla de verificación.
