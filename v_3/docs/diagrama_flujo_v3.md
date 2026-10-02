# Diagrama de flujo de la V3, por proceso

Cada proceso de la V3 se dibuja como un **chip** con pines de entrada y salida, al estilo de
microcontroladores en una placa. Sirve para analizar el diseño: qué entra y qué sale de cada
proceso, y con quién conecta. Fuentes: `mapa_v2.md` (D1–D9, al 2026-09-30), `arranque_v3.md`
(opción D5-A, que ya quedó decidida) y `../README.md`.

## Cómo leerlo

- **Un color por proceso.** Cada nodo lleva el color del proceso donde corre. El gris no es un
  proceso: son periféricos, archivos o el usuario. Aparecen solo como extremo de un cable,
  nunca como paso de un flujo.
- **Pines.** Cada pin tiene un nombre único, que se repite igual en los dos extremos del cable,
  como una etiqueta de red en un esquemático. Por ejemplo, OUT `enter_pulsado` en UNO se conecta
  con IN `enter_pulsado` en App.
  - Entrada: paralelogramo inclinado a la derecha, con el texto `IN`.
  - Salida: paralelogramo inclinado a la izquierda, con el texto `OUT`.
  - Entrada y salida (**E/S**): hexágono. Solo para interfaces que por naturaleza van en los
    dos sentidos: la base de datos, un candado del sistema operativo o una ventana que el
    usuario ve y teclea.
- **Supuestos.** Donde el proceso está decidido pero el mecanismo todavía no (D2, D3, D4), el
  nodo dice «(supuesto: …)». Ningún nodo queda sin proceso.
- Debajo de cada chip hay una tabla de pines. Al final están la placa completa y la
  verificación de que cada OUT tiene su IN.

```mermaid
flowchart LR
    L1["App<br/>proceso padre, venv"]:::app
    L2["soffice<br/>LibreOffice + main.ods"]:::sof
    L3["UNO<br/>Python de LibreOffice"]:::uno
    L4["admin_botones<br/>venv, Qt"]:::adm
    L5["camera_viewer<br/>caja negra"]:::cam
    L6["camera_viewer.archiver<br/>caja negra"]:::arc
    L7["No es proceso:<br/>usuario, periférico o archivo"]:::ext
    P1[/"IN pin de entrada"/]:::app
    P2[\"OUT pin de salida"\]:::app
    P3{{"E/S pin de ida y vuelta"}}:::app

    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef sof fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef uno fill:#ccfbf1,stroke:#0f766e,color:#042f2e,stroke-width:2px
    classDef adm fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef cam fill:#fef3c7,stroke:#b45309,color:#451a03,stroke-width:2px
    classDef arc fill:#ffe4e6,stroke:#be123c,color:#4c0519,stroke-width:2px
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px,stroke-dasharray:4 3
```

**Hijos de App:** soffice, UNO, camera_viewer.archiver, camera_viewer y admin_botones. App es
el único que lanza procesos (D5-A). Hay una **propuesta** para que admin_botones deje de ser
hijo (ver sección 6).

## 1. App (proceso padre)

```mermaid
flowchart LR
    iInicio[/"IN inicio"/]:::app
    iCajaLib[/"IN caja_liberada"/]:::app
    iPedirCaja[/"IN pedir_caja"/]:::app
    iUnoListo[/"IN uno_listo"/]:::app
    iEnter[/"IN enter_pulsado"/]:::app
    iTab[/"IN tab_pulsado"/]:::app
    iBoton[/"IN boton_pulsado"/]:::app
    iDocCerrado[/"IN documento_cerrado"/]:::app
    iSofSalio[/"IN soffice_salio"/]:::app
    iUnoSalio[/"IN uno_salio"/]:::app
    iHijosSalio[/"IN archivador_salio,<br/>camaras_salio, admin_salio"/]:::app
    iLogs[/"IN log_soffice, log_uno,<br/>log_archivador, log_camaras, log_admin"/]:::app

    ioCandUsr{{"E/S candado_usuario"}}:::app
    ioCandCaja{{"E/S candado_caja"}}:::app
    ioDb{{"E/S db"}}:::app
    ioUi{{"E/S ui_app"}}:::app

    subgraph APP["App — lanzador, lógica y ventanas Qt"]
        A1["Abre el log de esta ejecución"]:::app
        A2{"¿Ya hay una App de este usuario?<br/>(D8)"}:::app
        A2x(["Avisa y sale<br/>(supuesto: o trae la otra al frente)"]):::app
        A3{"¿Encuentra LibreOffice?<br/>PATH o registro (D9)"}:::app
        A3x(["Aviso Qt claro y sale"]):::app
        A4{"¿Otra App tiene la caja<br/>del equipo? (D8)"}:::app
        A4b["Le pide cierre ordenado y espera<br/>(tiempo máximo: pendiente)"]:::app
        A5["Toma la caja; registra usuario<br/>y sesión en ventas.db"]:::app
        A6["Lanza el archivador"]:::app
        A7["modo = normal (en RAM)"]:::app
        A8["Prepara main.ods del usuario:<br/>copia la plantilla (D7) y la hornea<br/>(supuesto: D4 = prebake con odfpy)"]:::app
        A9["Lanza soffice con pipe<br/>por usuario y --norestore"]:::app
        A10["Lanza el proceso UNO<br/>(pipe, dirección y token)"]:::app
        A11["Espera uno_listo; publica botones<br/>y manda el modo y las filas"]:::app
        V1["ControladorVenta: agregar, cobrar,<br/>registrar código, abrir caja<br/>(supuesto: D2 = lógica en App)"]:::app
        V1q["Diálogos Qt: cobro, precio, código"]:::app
        V2["Busca en el catálogo<br/>y muestra el selector Qt"]:::app
        V3{"¿Qué botón?"}:::app
        V4["Cambio de modo:<br/>ventas_dia o normal, relanzar = sí"]:::app
        V5["Acciones de acciones/*.py<br/>(caja, carrito, códigos…)"]:::app
        V6["Cada 0.5 s: ¿cambiaron los botones<br/>en ventas.db? (admin_botones)"]:::app
        C1["Cierre pedido por otra App:<br/>registra la sesión como cerrada y por quién<br/>(carrito a medias: pendiente)"]:::app
        F1{"¿Por qué terminó soffice?"}:::app
        F2{"¿Menos de 2 relanzamientos<br/>en 600 s? (contador en RAM)"}:::app
        U1{"¿soffice sigue vivo?"}:::app
        F3["Cierra la sesión en ventas.db"]:::app
        F4["Detiene el archivador,<br/>libera la caja y el candado, y sale"]:::app
        LG["Escribe cada línea con<br/>proceso, pid y hora"]:::app
    end

    oLog[\"OUT log"\]:::app
    oMainOds[\"OUT main_ods"\]:::app
    oArrSof[\"OUT arrancar_soffice"\]:::app
    oArrUno[\"OUT arrancar_uno"\]:::app
    oPublicar[\"OUT publicar_botones"\]:::app
    oPintar[\"OUT pintar"\]:::app
    oEscribir[\"OUT escribir_producto"\]:::app
    oEnfocar[\"OUT enfocar_calc"\]:::app
    oCerrarLO[\"OUT cerrar_libreoffice"\]:::app
    oArrArch[\"OUT arrancar_archivador"\]:::app
    oTermArch[\"OUT terminar_archivador"\]:::app
    oArrCam[\"OUT arrancar_camaras"\]:::app
    oArrAdm[\"OUT arrancar_admin"\]:::app
    oTicket[\"OUT imprimir_ticket"\]:::app
    oCajon[\"OUT abrir_cajon"\]:::app
    oEtiqueta[\"OUT imprimir_etiqueta"\]:::app
    oPedirCaja[\"OUT pedir_caja"\]:::app
    oCajaLib[\"OUT caja_liberada"\]:::app

    %% Arranque
    iInicio --> A1 --> A2
    A1 --> oLog
    A2 <--> ioCandUsr
    A2 -- "sí" --> A2x
    A2 -- "no" --> A3
    A3 -- "no" --> A3x
    A3 -- "sí" --> A4
    A4 <--> ioCandCaja
    A4 -- "sí" --> A4b --> oPedirCaja
    iCajaLib --> A5
    A4 -- "no" --> A5
    A5 <--> ioDb
    A5 --> A6 --> oArrArch
    A6 --> A7 --> A8 --> oMainOds
    A8 --> A9 --> oArrSof
    A9 --> A10 --> oArrUno
    iUnoListo --> A11
    A11 --> oPublicar
    A11 --> oPintar

    %% Atención de eventos
    iEnter --> V1
    V1 <--> V1q <--> ioUi
    V1 <--> ioDb
    V1 --> oTicket
    V1 --> oCajon
    V1 --> oPintar
    V1 --> oEnfocar
    iTab --> V2 <--> ioUi
    V2 --> oEscribir
    V2 --> oEnfocar
    iBoton --> V3
    V3 -- "VER CÁMARAS" --> oArrCam
    V3 -- "ADMINISTRAR ADMINS" --> oArrAdm
    V3 -- "ver_ventas / REGRESAR" --> V4 --> oCerrarLO
    V3 -- "otros" --> V5
    V5 <--> ioDb
    V5 <--> ioUi
    V5 --> oPintar
    V5 --> oCajon
    V5 --> oEtiqueta
    V6 <--> ioDb
    V6 --> oPublicar

    %% Cierre pedido por otra App (D8)
    iPedirCaja --> C1 --> oCerrarLO
    C1 <--> ioDb

    %% Fin de soffice o de UNO
    iDocCerrado --> F1
    iSofSalio --> F1
    iUnoSalio --> U1
    U1 -- "sí: relanza solo UNO" --> A10
    U1 -- "no" --> F1
    F1 -- "cambio de modo" --> A8
    F1 -- "caída" --> F2
    F2 -- "sí" --> A8
    F2 -- "no" --> F3
    F1 -- "cierre normal o caja cedida" --> F3
    F3 <--> ioDb
    F3 --> F4
    F4 --> oTermArch
    F4 --> oCajaLib
    F4 <--> ioCandCaja

    %% Log único
    iLogs --> LG --> oLog
    iHijosSalio --> LG

    style APP fill:#f0fdf4,stroke:#15803d,stroke-width:3px,color:#0b3d1c
    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
```

Notas:

- **Todos los nodos son App**, incluidas las ventanas Qt: son hilos o ventanas del mismo
  proceso, no hijos.
- **`caja_liberada` solo tiene sentido en la App que cedió la caja.** Si nadie pidió la caja,
  F4 libera `candado_caja` y ahí se acaba. La App que llega se entera por el pin
  `caja_liberada` o por el propio candado.
- **Cambio de modo.** Con D4 = prebake hay que reabrir soffice (F1 → A8). Si D4 termina siendo
  «pintar en vivo», V4 mandaría `pintar` con el modo nuevo y no haría falta cerrar LibreOffice.

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `inicio` | IN | Argumentos del entry point | Usuario/SO `abrir_icono` | Creación de proceso (menú del sistema, menú Inicio) |
| `candado_usuario` | E/S | Tomar o comprobar el candado | SO | Bloqueo de archivo en la carpeta de ejecución del usuario; se libera solo si el proceso muere |
| `candado_caja` | E/S | Tomar o comprobar la caja del equipo | Carpeta de datos compartida | Bloqueo de archivo en la carpeta compartida (supuesto: el mismo candado sirve para saber si otra App la tiene) |
| `pedir_caja` | OUT | Quién la pide y cuándo | `pedir_caja` IN de la App anterior | Archivo en la carpeta compartida (punto de encuentro de D8) |
| `pedir_caja` | IN | Quién la pide | `pedir_caja` OUT de la App que llega | Ídem |
| `caja_liberada` | OUT | Sesión cerrada, por quién | `caja_liberada` IN de la App que llega | Ídem, o el candado queda libre |
| `caja_liberada` | IN | Ídem | `caja_liberada` OUT de la App anterior | Ídem |
| `db` | E/S | Ventas, usuarios, sesión, catálogo, códigos, botones | `ventas.db` | `sqlite3` |
| `ui_app` | E/S | Diálogos, selector, avisos | Usuario | Ventanas Qt |
| `log` | OUT | Líneas con proceso, pid y hora | Archivo de log de la ejecución | Archivo |
| `main_ods` | OUT | `main.ods` del usuario, horneado | soffice `main_ods` | Archivo en la carpeta del usuario |
| `arrancar_soffice` | OUT | `--accept=pipe,name=…`, `--norestore`, ruta de `main.ods` | soffice `arrancar_soffice` | Creación de proceso (argumentos) |
| `soffice_salio` | IN | Código de salida | soffice `soffice_salio` | Espera del proceso hijo |
| `log_soffice` | IN | stdout/stderr | soffice `log_soffice` | Tubería del proceso hijo |
| `arrancar_uno` | OUT | Nombre del pipe, dirección y token del socket | UNO `arrancar_uno` | Creación de proceso (argumentos) |
| `uno_listo` | IN | Documento encontrado, handlers registrados | UNO `uno_listo` | Socket local |
| `enter_pulsado` | IN | Fila de entrada, texto del tramo, ¿es escaneo? | UNO `enter_pulsado` | Socket local |
| `tab_pulsado` | IN | Prefijo escrito | UNO `tab_pulsado` | Socket local |
| `boton_pulsado` | IN | id del botón | UNO `boton_pulsado` | Socket local |
| `documento_cerrado` | IN | Motivo: cierre normal o caída | UNO `documento_cerrado` | Socket local |
| `uno_salio` | IN | Código de salida | UNO `uno_salio` | Espera del proceso hijo (y el socket se corta) |
| `log_uno` | IN | stdout/stderr, tracebacks | UNO `log_uno` | Tubería del proceso hijo |
| `pintar` | OUT | Modo; filas de entrada, carrito o ventas; fila de evento | UNO `pintar` | Socket local |
| `escribir_producto` | OUT | Producto elegido para B4 | UNO `escribir_producto` | Socket local |
| `publicar_botones` | OUT | Lista (id, etiqueta) | UNO `publicar_botones` | Socket local |
| `enfocar_calc` | OUT | Devolver el foco a Calc y a B4 | UNO `enfocar_calc` | Socket local |
| `cerrar_libreoffice` | OUT | Orden de cierre | UNO `cerrar_libreoffice` | Socket local |
| `arrancar_archivador` | OUT | Módulo a correr, entorno | archivador `arrancar_archivador` | Creación de proceso |
| `terminar_archivador` | OUT | Cierre ordenado (5 s, luego forzado) | archivador `terminar_archivador` | `terminate()` del proceso (SIGTERM en Linux) |
| `archivador_salio` | IN | Código de salida | archivador | Espera del proceso hijo |
| `log_archivador` | IN | stdout/stderr | archivador | Tubería del proceso hijo |
| `arrancar_camaras` | OUT | Módulo a correr, entorno | camera_viewer `arrancar_camaras` | Creación de proceso |
| `camaras_salio` | IN | Código de salida | camera_viewer | Espera del proceso hijo |
| `log_camaras` | IN | stdout/stderr | camera_viewer | Tubería del proceso hijo |
| `arrancar_admin` | OUT | Módulo a correr, entorno | admin_botones `arrancar_admin` | Creación de proceso |
| `admin_salio` | IN | Código de salida | admin_botones | Espera del proceso hijo |
| `log_admin` | IN | stdout/stderr | admin_botones | Tubería del proceso hijo |
| `imprimir_ticket` | OUT | Líneas del ticket, QR | Impresora de tickets | Driver / puerto (como `hardware/ticket_printer.py`) |
| `abrir_cajon` | OUT | Pulso de apertura | Cajón, a través de la impresora de tickets | Ídem |
| `imprimir_etiqueta` | OUT | Imagen del código de barras | Impresora de etiquetas | Como `hardware/barcode_printer.py` |

## 2. soffice (LibreOffice con `main.ods`)

Hijo de App. No se programa: es LibreOffice. Los nodos describen lo que hace, para que se vean
sus pines.

```mermaid
flowchart LR
    iArr[/"IN arrancar_soffice"/]:::sof
    iOds[/"IN main_ods"/]:::sof
    iApi[/"IN api_hoja"/]:::sof
    iTecl[/"IN teclado_raton"/]:::sof

    subgraph SOF["soffice — LibreOffice Calc"]
        S1["Arranca<br/>(a medir: perfil propio con -env:UserInstallation)"]:::sof
        S2["Abre el main.ods del usuario"]:::sof
        S3["Acepta conexiones URP<br/>en el pipe del usuario"]:::sof
        S4["Muestra la hoja y los botones"]:::sof
        S5["Pasa cada tecla a los<br/>XKeyHandler registrados"]:::sof
        S6["Avisa del clic a los<br/>XActionListener del botón<br/>(supuesto: D3 = b)"]:::sof
        S7["Ejecuta las llamadas:<br/>celdas, protección, controles,<br/>setModified, terminate"]:::sof
        S8["Se cierra la ventana, llega<br/>terminate o LibreOffice se cae"]:::sof
        S9["Termina el proceso"]:::sof
    end

    oUrp[\"OUT urp_listo"\]:::sof
    oTecla[\"OUT tecla"\]:::sof
    oClic[\"OUT clic"\]:::sof
    oMurio[\"OUT documento_murio"\]:::sof
    oPant[\"OUT pantalla_hoja"\]:::sof
    oSalio[\"OUT soffice_salio"\]:::sof
    oLog[\"OUT log_soffice"\]:::sof

    iArr --> S1 --> S2
    iOds --> S2
    S2 --> S3 --> oUrp
    S2 --> S4 --> oPant
    iTecl --> S5 --> oTecla
    iTecl --> S6 --> oClic
    iApi --> S7 --> S4
    S7 --> S8
    iTecl --> S8
    S8 --> oMurio
    S8 --> S9 --> oSalio
    S1 --> oLog

    style SOF fill:#eff6ff,stroke:#1d4ed8,stroke-width:3px,color:#0b1f4d
    classDef sof fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
```

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `arrancar_soffice` | IN | Argumentos | App `arrancar_soffice` | Creación de proceso |
| `main_ods` | IN | Documento del usuario | App `main_ods` | Archivo |
| `api_hoja` | IN | Llamadas a la API | UNO `api_hoja` | URP por el pipe con nombre |
| `teclado_raton` | IN | Teclas (también las del escáner) y clics | Usuario `teclado_escaner_raton` | Eventos del sistema de ventanas |
| `urp_listo` | OUT | El pipe acepta conexiones | UNO `urp_listo` | URP (la conexión se logra o falla; UNO reintenta) |
| `tecla` | OUT | `KeyEvent` | UNO `tecla` | Callback URP `XKeyHandler.keyPressed` |
| `clic` | OUT | Control pulsado | UNO `clic` | Callback URP `XActionListener.actionPerformed` (supuesto: D3 = b) |
| `documento_murio` | OUT | El documento o el puente dejan de responder | UNO `documento_murio` | Excepción en la siguiente llamada (supuesto: sondeo como en la V2) |
| `pantalla_hoja` | OUT | La hoja | Usuario | Ventana de LibreOffice |
| `soffice_salio` | OUT | Código de salida | App `soffice_salio` | Fin del proceso hijo |
| `log_soffice` | OUT | stdout/stderr | App `log_soffice` | Tubería |

**Con D3 = (a), el `.evt` y el sondeo:** el pin `clic` sigue yendo de soffice a UNO, pero el
mecanismo cambia. Una macro Basic del documento escribe un `.evt` en la carpeta de ejecución
del usuario y UNO lo sondea cada 0.5 s. En ese caso `main.ods` tiene que llevar `Module1` y las
macros deben estar habilitadas.

## 3. UNO (Python de LibreOffice)

Hijo de App. Solo `uno` y la biblioteca estándar. Pinta la hoja y captura teclas y clics.

```mermaid
flowchart LR
    iArr[/"IN arrancar_uno"/]:::uno
    iUrp[/"IN urp_listo"/]:::uno
    iTecla[/"IN tecla"/]:::uno
    iClic[/"IN clic"/]:::uno
    iMurio[/"IN documento_murio"/]:::uno
    iPintar[/"IN pintar"/]:::uno
    iEscribir[/"IN escribir_producto"/]:::uno
    iPublicar[/"IN publicar_botones"/]:::uno
    iEnfocar[/"IN enfocar_calc"/]:::uno
    iCerrar[/"IN cerrar_libreoffice"/]:::uno

    subgraph UNOP["UNO — puente con Calc"]
        U1["Lee los argumentos:<br/>pipe, dirección y token"]:::uno
        U2["Se conecta a soffice por el pipe<br/>(con reintentos mientras abre)"]:::uno
        U3["Busca main.ods y se conecta<br/>al socket de App con el token"]:::uno
        U4["Registra el XKeyHandler<br/>(Enter, Tab, escáner)"]:::uno
        K1["Anota la hora de llegada de la tecla<br/>y la suma al tramo<br/>(un hueco mayor de 100 ms lo reinicia)"]:::uno
        K2{"¿Qué tecla?"}:::uno
        K3["Regla D1: al menos 3 caracteres<br/>y promedio ≤ 40 ms → escaneo<br/>(supuesto: la regla corre en UNO)"]:::uno
        K4["Lee la fila de entrada<br/>y devuelve el cursor a B4"]:::uno
        K5["Deja pasar la tecla a Calc"]:::uno
        P1["Desprotege, escribe y protege<br/>(SheetAdmin + Table)"]:::uno
        B1["Crea los botones y un<br/>XActionListener por botón<br/>(supuesto: D3 = b)"]:::uno
        B2["Traduce el control a su id"]:::uno
        W1["Cada 1 s: lee Title<br/>y hace setModified(False)<br/>(supuesto: como en la V2)"]:::uno
        W2["Clasifica: cierre normal<br/>o caída"]:::uno
        T1["desktop.terminate()"]:::uno
        X1["Sale"]:::uno
    end

    oListo[\"OUT uno_listo"\]:::uno
    oEnter[\"OUT enter_pulsado"\]:::uno
    oTab[\"OUT tab_pulsado"\]:::uno
    oBoton[\"OUT boton_pulsado"\]:::uno
    oDoc[\"OUT documento_cerrado"\]:::uno
    oApi[\"OUT api_hoja"\]:::uno
    oSalio[\"OUT uno_salio"\]:::uno
    oLog[\"OUT log_uno"\]:::uno

    iArr --> U1 --> U2
    iUrp --> U2
    U2 --> U3 --> U4 --> oApi
    U4 --> oListo
    iTecla --> K1 --> K2
    K2 -- "Tab" --> oTab
    K2 -- "Enter" --> K3 --> K4 --> oEnter
    K4 --> oApi
    K2 -- "otra" --> K5
    iPintar --> P1
    iEscribir --> P1
    iEnfocar --> P1
    P1 --> oApi
    iPublicar --> B1 --> oApi
    iClic --> B2 --> oBoton
    U4 --> W1 --> oApi
    iMurio --> W2 --> oDoc
    W2 --> X1 --> oSalio
    iCerrar --> T1 --> oApi
    U1 --> oLog

    style UNOP fill:#f0fdfa,stroke:#0f766e,stroke-width:3px,color:#042f2e
    classDef uno fill:#ccfbf1,stroke:#0f766e,color:#042f2e,stroke-width:2px
```

| Pin | Dir. | Datos | Conecta con | Mecanismo |
|---|---|---|---|---|
| `arrancar_uno` | IN | Pipe, dirección y token | App `arrancar_uno` | Argumentos del proceso |
| `urp_listo` | IN | Conexión lograda | soffice `urp_listo` | URP |
| `tecla` | IN | `KeyEvent` | soffice `tecla` | Callback `XKeyHandler` |
| `clic` | IN | Control | soffice `clic` | Callback `XActionListener` (supuesto: D3 = b) |
| `documento_murio` | IN | Excepción | soffice `documento_murio` | API UNO |
| `pintar` | IN | Modo, filas, fila de evento | App `pintar` | Socket local |
| `escribir_producto` | IN | Producto | App `escribir_producto` | Socket local |
| `publicar_botones` | IN | Lista (id, etiqueta) | App `publicar_botones` | Socket local |
| `enfocar_calc` | IN | Orden | App `enfocar_calc` | Socket local |
| `cerrar_libreoffice` | IN | Orden | App `cerrar_libreoffice` | Socket local |
| `uno_listo` | OUT | Documento encontrado y handlers registrados | App `uno_listo` | Socket local |
| `enter_pulsado` | OUT | Fila de entrada, texto del tramo, ¿es escaneo? | App `enter_pulsado` | Socket local |
| `tab_pulsado` | OUT | Prefijo | App `tab_pulsado` | Socket local |
| `boton_pulsado` | OUT | id | App `boton_pulsado` | Socket local |
| `documento_cerrado` | OUT | Motivo | App `documento_cerrado` | Socket local |
| `api_hoja` | OUT | Llamadas a la API | soffice `api_hoja` | URP por el pipe |
| `uno_salio` | OUT | Código de salida | App `uno_salio` | Fin del proceso hijo |
| `log_uno` | OUT | stdout/stderr, tracebacks en texto plano | App `log_uno` | Tubería |

## 4. camera_viewer.archiver (caja negra)

Hijo de App desde el arranque hasta el cierre. Es de la otra instancia: aquí solo se ven sus
pines.

```mermaid
flowchart LR
    iArr[/"IN arrancar_archivador"/]:::arc
    iTerm[/"IN terminar_archivador"/]:::arc
    subgraph ARC["camera_viewer.archiver"]
        R1["Caja negra<br/>(otra instancia; tiene su propio candado de instancia única)"]:::arc
    end
    ioDvr{{"E/S dvr_archivador"}}:::arc
    oSalio[\"OUT archivador_salio"\]:::arc
    oLog[\"OUT log_archivador"\]:::arc
    iArr --> R1
    iTerm --> R1
    R1 <--> ioDvr
    R1 --> oSalio
    R1 --> oLog
    style ARC fill:#fff1f2,stroke:#be123c,stroke-width:3px,color:#4c0519
    classDef arc fill:#ffe4e6,stroke:#be123c,color:#4c0519,stroke-width:2px
```

| Pin | Dir. | Conecta con | Mecanismo |
|---|---|---|---|
| `arrancar_archivador` | IN | App | Creación de proceso |
| `terminar_archivador` | IN | App | `terminate()` (SIGTERM en Linux) |
| `dvr_archivador` | E/S | DVR y disco | Propio de la caja negra |
| `archivador_salio` | OUT | App | Fin del proceso |
| `log_archivador` | OUT | App | Tubería |

## 5. camera_viewer (caja negra)

Hijo de App, lanzado con el botón VER CÁMARAS.

```mermaid
flowchart LR
    iArr[/"IN arrancar_camaras"/]:::cam
    subgraph CAM["camera_viewer"]
        M1["Caja negra (otra instancia)"]:::cam
    end
    ioUi{{"E/S ui_camaras"}}:::cam
    ioDvr{{"E/S dvr_camaras"}}:::cam
    oSalio[\"OUT camaras_salio"\]:::cam
    oLog[\"OUT log_camaras"\]:::cam
    iArr --> M1
    M1 <--> ioUi
    M1 <--> ioDvr
    M1 --> oSalio
    M1 --> oLog
    style CAM fill:#fffbeb,stroke:#b45309,stroke-width:3px,color:#451a03
    classDef cam fill:#fef3c7,stroke:#b45309,color:#451a03,stroke-width:2px
```

| Pin | Dir. | Conecta con | Mecanismo |
|---|---|---|---|
| `arrancar_camaras` | IN | App | Creación de proceso |
| `ui_camaras` | E/S | Usuario | Ventana Qt |
| `dvr_camaras` | E/S | DVR | Propio de la caja negra |
| `camaras_salio` | OUT | App | Fin del proceso |
| `log_camaras` | OUT | App | Tubería |

No hay pin `terminar_camaras`. En la V2, la ventana de cámaras sigue abierta aunque se cierre el
POS; aquí se deja igual (ver «Discrepancias encontradas», punto 4).

## 6. admin_botones

Hijo de App, lanzado con el botón ADMINISTRAR ADMINS (solo lo ve `ADMIN_RAIZ`).

```mermaid
flowchart LR
    iArr[/"IN arrancar_admin"/]:::adm
    subgraph ADM["admin_botones"]
        D1["Ventana Qt: botones<br/>y visibilidad por usuario"]:::adm
        D2["Guarda los cambios"]:::adm
    end
    ioUi{{"E/S ui_admin"}}:::adm
    ioDb{{"E/S db_botones"}}:::adm
    oSalio[\"OUT admin_salio"\]:::adm
    oLog[\"OUT log_admin"\]:::adm
    iArr --> D1 --> D2 --> ioDb
    D1 <--> ioUi
    D1 <--> ioDb
    D2 --> oLog
    D1 --> oSalio
    style ADM fill:#f5f3ff,stroke:#6d28d9,stroke-width:3px,color:#2e1065
    classDef adm fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
```

| Pin | Dir. | Conecta con | Mecanismo |
|---|---|---|---|
| `arrancar_admin` | IN | App | Creación de proceso |
| `ui_admin` | E/S | Usuario | Ventana Qt |
| `db_botones` | E/S | `ventas.db` | `sqlite3` |
| `admin_salio` | OUT | App | Fin del proceso |
| `log_admin` | OUT | App | Tubería |

**Propuesta: que admin_botones sea una ventana dentro de App, no un hijo.** Motivos:

- **Ya no hay razón para un proceso aparte.** En la V2 existe porque `main.py` corría en el
  Python de LibreOffice, sin Qt, y como root (su lanzador baja privilegios). En la V3, App ya es
  el venv con Qt y no corre como root.
- **Un solo dueño de `ventas.db`**, que es lo que busca D2. Hoy admin_botones escribe en la base
  por su cuenta, y App solo se entera sondeando cada 0.5 s (V6, `revisar_cambios`). Como ventana
  de App, al guardar se llamaría directo a `publicar_botones`, sin sondeo.
- **Menos pines y menos piezas.** Desaparecen `arrancar_admin`, `admin_salio`, `log_admin` y
  `db_botones`, junto con su lanzador y la búsqueda de «ya hay una ventana abierta».

El costo: un fallo en esa ventana ya no queda aislado del POS. Con la red de seguridad de
excepciones que ya usan los hilos de la V2, el riesgo es bajo. Si se acepta, el bloque 6 se
convierte en nodos de App y la placa pierde un chip.

## 7. Placa completa

Solo los bloques y los cables. Los mensajes del socket entre App y UNO se agrupan en dos buses
(uno por sentido); cada mensaje tiene su fila en las tablas de arriba.

```mermaid
flowchart LR
    USR["Usuario, teclado, escáner y ratón"]:::ext
    SO["Sistema operativo<br/>(menú, candados)"]:::ext
    APP2["App de otro usuario<br/>(misma App, otra instancia)"]:::app
    APP["App"]:::app
    SOF["soffice"]:::sof
    UNOB["UNO"]:::uno
    ARC["camera_viewer.archiver"]:::arc
    CAM["camera_viewer"]:::cam
    ADM["admin_botones"]:::adm
    DB[("ventas.db")]:::ext
    COMP["Carpeta de datos compartida"]:::ext
    LOG["Archivo de log de la ejecución"]:::ext
    IMP["Impresora de tickets y cajón"]:::ext
    ETQ["Impresora de etiquetas"]:::ext
    DVR["DVR y disco"]:::ext

    SO -- "inicio" --> APP
    APP <-- "candado_usuario" --> SO
    APP <-- "candado_caja" --> COMP
    APP -- "pedir_caja" --> APP2
    APP2 -- "caja_liberada" --> APP
    APP <-- "ui_app" --> USR
    APP <-- "db" --> DB
    APP -- "log" --> LOG
    APP -- "imprimir_ticket, abrir_cajon" --> IMP
    APP -- "imprimir_etiqueta" --> ETQ

    APP -- "arrancar_soffice, main_ods" --> SOF
    SOF -- "soffice_salio, log_soffice" --> APP
    APP -- "arrancar_uno" --> UNOB
    APP -- "bus: pintar, escribir_producto,<br/>publicar_botones, enfocar_calc,<br/>cerrar_libreoffice" --> UNOB
    UNOB -- "bus: uno_listo, enter_pulsado,<br/>tab_pulsado, boton_pulsado,<br/>documento_cerrado" --> APP
    UNOB -- "uno_salio, log_uno" --> APP
    UNOB -- "api_hoja" --> SOF
    SOF -- "urp_listo, tecla, clic,<br/>documento_murio" --> UNOB
    USR -- "teclado_escaner_raton" --> SOF
    SOF -- "pantalla_hoja" --> USR

    APP -- "arrancar_archivador,<br/>terminar_archivador" --> ARC
    ARC -- "archivador_salio, log_archivador" --> APP
    ARC <-- "dvr_archivador" --> DVR
    APP -- "arrancar_camaras" --> CAM
    CAM -- "camaras_salio, log_camaras" --> APP
    CAM <-- "ui_camaras" --> USR
    CAM <-- "dvr_camaras" --> DVR
    APP -- "arrancar_admin" --> ADM
    ADM -- "admin_salio, log_admin" --> APP
    ADM <-- "ui_admin" --> USR
    ADM <-- "db_botones" --> DB

    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef sof fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef uno fill:#ccfbf1,stroke:#0f766e,color:#042f2e,stroke-width:2px
    classDef adm fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef cam fill:#fef3c7,stroke:#b45309,color:#451a03,stroke-width:2px
    classDef arc fill:#ffe4e6,stroke:#be123c,color:#4c0519,stroke-width:2px
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px,stroke-dasharray:4 3
```

`pedir_caja` y `caja_liberada` son pines de la misma App: la que llega usa OUT `pedir_caja` e
IN `caja_liberada`; la que cede usa IN `pedir_caja` y OUT `caja_liberada`. En la placa se
dibujan entre dos instancias.

## 8. Verificación de pines

Cada cable, con su OUT y su IN. Los extremos grises (usuario, SO, archivos, periféricos) no son
procesos, pero se cuentan para que ningún pin quede suelto.

| # | OUT (bloque) | IN (bloque) | Mecanismo | ¿Pareja? |
|---|---|---|---|---|
| 1 | `abrir_icono` (SO) | `inicio` (App) | Creación de proceso | Sí |
| 2 | `arrancar_soffice` (App) | `arrancar_soffice` (soffice) | Creación de proceso | Sí |
| 3 | `main_ods` (App) | `main_ods` (soffice) | Archivo | Sí |
| 4 | `soffice_salio` (soffice) | `soffice_salio` (App) | Fin de proceso | Sí |
| 5 | `log_soffice` (soffice) | `log_soffice` (App) | Tubería | Sí |
| 6 | `arrancar_uno` (App) | `arrancar_uno` (UNO) | Creación de proceso | Sí |
| 7 | `pintar` (App) | `pintar` (UNO) | Socket | Sí |
| 8 | `escribir_producto` (App) | `escribir_producto` (UNO) | Socket | Sí |
| 9 | `publicar_botones` (App) | `publicar_botones` (UNO) | Socket | Sí |
| 10 | `enfocar_calc` (App) | `enfocar_calc` (UNO) | Socket | Sí |
| 11 | `cerrar_libreoffice` (App) | `cerrar_libreoffice` (UNO) | Socket | Sí |
| 12 | `uno_listo` (UNO) | `uno_listo` (App) | Socket | Sí |
| 13 | `enter_pulsado` (UNO) | `enter_pulsado` (App) | Socket | Sí |
| 14 | `tab_pulsado` (UNO) | `tab_pulsado` (App) | Socket | Sí |
| 15 | `boton_pulsado` (UNO) | `boton_pulsado` (App) | Socket | Sí |
| 16 | `documento_cerrado` (UNO) | `documento_cerrado` (App) | Socket | Sí |
| 17 | `uno_salio` (UNO) | `uno_salio` (App) | Fin de proceso | Sí |
| 18 | `log_uno` (UNO) | `log_uno` (App) | Tubería | Sí |
| 19 | `api_hoja` (UNO) | `api_hoja` (soffice) | URP | Sí |
| 20 | `urp_listo` (soffice) | `urp_listo` (UNO) | URP | Sí |
| 21 | `tecla` (soffice) | `tecla` (UNO) | Callback URP | Sí |
| 22 | `clic` (soffice) | `clic` (UNO) | Callback URP (supuesto: D3 = b) | Sí |
| 23 | `documento_murio` (soffice) | `documento_murio` (UNO) | API UNO | Sí |
| 24 | `teclado_escaner_raton` (usuario) | `teclado_raton` (soffice) | Sistema de ventanas | Sí (nombres distintos a propósito: el mismo cable también lleva el escáner) |
| 25 | `pantalla_hoja` (soffice) | usuario | Pantalla | Sí |
| 26 | `arrancar_archivador` (App) | `arrancar_archivador` (archivador) | Creación de proceso | Sí |
| 27 | `terminar_archivador` (App) | `terminar_archivador` (archivador) | `terminate()` | Sí |
| 28 | `archivador_salio` (archivador) | `archivador_salio` (App) | Fin de proceso | Sí |
| 29 | `log_archivador` (archivador) | `log_archivador` (App) | Tubería | Sí |
| 30 | `arrancar_camaras` (App) | `arrancar_camaras` (camera_viewer) | Creación de proceso | Sí |
| 31 | `camaras_salio` (camera_viewer) | `camaras_salio` (App) | Fin de proceso | Sí |
| 32 | `log_camaras` (camera_viewer) | `log_camaras` (App) | Tubería | Sí |
| 33 | `arrancar_admin` (App) | `arrancar_admin` (admin_botones) | Creación de proceso | Sí |
| 34 | `admin_salio` (admin_botones) | `admin_salio` (App) | Fin de proceso | Sí |
| 35 | `log_admin` (admin_botones) | `log_admin` (App) | Tubería | Sí |
| 36 | `pedir_caja` (App que llega) | `pedir_caja` (App anterior) | Carpeta compartida | Sí |
| 37 | `caja_liberada` (App anterior) | `caja_liberada` (App que llega) | Carpeta compartida | Sí |
| 38 | `imprimir_ticket` (App) | Impresora de tickets | Driver | Sí |
| 39 | `abrir_cajon` (App) | Cajón | Driver | Sí |
| 40 | `imprimir_etiqueta` (App) | Impresora de etiquetas | Driver | Sí |
| 41 | `log` (App) | Archivo de log | Archivo | Sí |

Pines E/S (sin dirección única): `candado_usuario` (App ↔ SO), `candado_caja` (App ↔ carpeta
compartida), `db` (App ↔ `ventas.db`), `db_botones` (admin_botones ↔ `ventas.db`), `ui_app`,
`ui_camaras`, `ui_admin` (↔ usuario), `dvr_archivador` y `dvr_camaras` (↔ DVR). Todos tienen
su otro extremo.

**Resultado: todos los OUT tienen su IN y al revés.** Los únicos puntos sueltos son deliberados
o están por decidir:

- **El código de salida de App no tiene IN**: nadie lo lee, porque App es el primer proceso y
  lo lanza el menú del sistema.
- **camera_viewer no tiene pin de cierre**: se deja igual que en la V2 (punto 4 de abajo).
- **Cambios de admin_botones.** No hay cable directo de admin_botones a App: App se entera
  leyendo `ventas.db` (V6). Es una dependencia indirecta por la base, no un pin. La propuesta de
  la sección 6 la elimina.

## Discrepancias encontradas

1. **`arranque_v3.md` quedó atrás de D8.** Su nota 4 y la fila «`asegurar_instancia_unica`» de
   la tabla V2 → V3 plantean «un usuario a la vez» como pregunta abierta. D8 ya lo decidió: una
   sola caja por equipo, «el último gana» y cierre ordenado pedido. Aquí se usó D8.
2. **Dónde se aplica la regla del escáner.** La sección 3 del mapa dice que UNO manda a App
   «el contenido de la fila de entrada y el ritmo de las teclas», lo que sugiere que App decide
   si fue escaneo. Aquí se dibujó con la regla en UNO (supuesto), porque la hora de cada tecla
   solo existe ahí y así no hay que mandar un mensaje por tecla. Las dos cosas son posibles; hay
   que elegir una.
3. **D8 no dice qué pasa si la App anterior no responde** a `pedir_caja`: por ejemplo, si está
   colgada o si su sesión gráfica está bloqueada. Si el proceso murió, el candado del SO ya
   quedó libre y no hay problema. Pero si sigue vivo y no contesta, «sin `kill`» deja a la App
   nueva esperando para siempre. Falta un tiempo máximo y qué hacer al vencer. Es aparte de lo
   que D8 ya marca como pendiente (el carrito a medias).
4. **camera_viewer sobrevive al POS.** En la V2, `atexit` solo detiene al archivador; la ventana
   de cámaras queda abierta. El mapa no dice si en la V3 se quiere igual. Aquí se dejó como en
   la V2, sin pin `terminar_camaras`.
5. **A la sección 3 del mapa le faltan mensajes.** No incluye `uno_listo` (el saludo inicial,
   necesario para saber cuándo mandar botones y filas) ni el modo dentro de `pintar`. Con D4 =
   prebake, UNO necesita saber el modo para engancharse a las tablas correctas.

## Validación de la sintaxis Mermaid

No se validó con una herramienta: en este equipo no hay `node` ni `npx`, y la regla es no
instalar nada global. Todas las etiquetas van entre comillas. Las formas de los pines
(`[/"…"/]`, `[\"…"\]`, `{{"…"}}`) y el uso de `style` sobre subgrafos son sintaxis estándar de
flowchart. Aun así, conviene abrirlo en GitHub, VS Code o mermaid.live antes de darlo por bueno.
