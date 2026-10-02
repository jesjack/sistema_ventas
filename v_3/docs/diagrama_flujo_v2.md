# Diagrama de flujo del sistema de ventas V2

Complemento visual de `mapa_v2.md`. Se levantó leyendo el mapa y el código de `v_2`
(`open_system.sh`, `libreofficeModules/Module1`, `main.py`, `nucleo/`, `services/`). Cada nodo
lleva el color de la propuesta del mapa para la V3.

## Leyenda

```mermaid
flowchart LR
    L1["UNO<br/>proceso de LibreOffice"]:::uno
    L2["App<br/>proceso del venv"]:::app
    L3["Los dos<br/>cada proceso con su copia"]:::dos
    L4["Decidir<br/>D1–D5 del mapa"]:::decidir
    L5["Acción del usuario o del sistema operativo<br/>(no es un nodo del mapa)"]:::externo

    classDef uno fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef dos fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef decidir fill:#ffedd5,stroke:#c2410c,color:#4a1d06,stroke-width:2px,stroke-dasharray:6 3
    classDef externo fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px
```

- Las flechas punteadas (`-.->`) son procesos que se lanzan aparte, en el venv, y no se esperan.
- Cuando un nodo es de la propuesta **Decidir**, el texto dice cuál decisión (D1–D5).
- Donde el mapa reparte un paso entre los dos procesos (App decide, UNO pinta), se dibujan dos
  nodos: uno para la decisión y otro para lo que se pinta en la hoja.

## 1. Arranque

```mermaid
flowchart TD
    A0(["Doble clic en el ícono / reinicio de la máquina"]):::externo
    A1["open_system.sh / .bat<br/>bucle del lanzador"]:::decidir
    A2{"¿Primera vuelta del bucle?"}:::decidir
    A3["Borra share/logs/modo_sistema.json<br/>(siempre arranca en modo normal)"]:::app
    A4["prebake_ventas.py en .venv<br/>hornea share/main.ods con odfpy<br/>· D4"]:::decidir
    A5["Borra el lock de main.ods<br/>solo si no hay soffice.bin del usuario"]:::decidir
    A6["libreoffice --accept puerto 2002 main.ods<br/>el lanzador espera a que termine<br/>· D5"]:::decidir
    A7["Macro Basic Module1.Main<br/>TPV_PrepararComunicacion + TPV_LimpiarBotones<br/>· D5"]:::decidir
    A8["Shell sin esperar:<br/>Linux: sudo /usr/bin/python3 main.py<br/>Windows: python.exe de LibreOffice main.py<br/>· D5"]:::decidir

    A0 --> A1 --> A2
    A2 -- "sí" --> A3 --> A4
    A2 -- "no (relanzamiento)" --> A4
    A4 --> A5 --> A6 --> A7 --> A8

    B1["main.py: activar_log_de_depuracion<br/>+ activar_volcado_de_hilos (SIGUSR1)"]:::dos
    B2{"¿Se puede importar uno?"}:::uno
    B2x(["sys.exit(1)"]):::uno
    B3["rich.traceback.install<br/>(se reemplaza por tracebacks de stdlib en los dos)"]:::dos
    B4["nucleo.arranque.ejecutar()"]:::app
    B5{"asegurar_instancia_unica<br/>¿el puerto 2002 es de este usuario?"}:::app
    B5x(["Cierra el sistema del otro usuario,<br/>deja relanzar.flag y sys.exit(0)"]):::app
    B6["_iniciar_archivador_de_camaras"]:::app
    P1[["camera_viewer.archiver<br/>(.venv, segundo plano, todo el tiempo)"]]:::app
    B7["conectar_libreoffice + obtener_documento_calc"]:::uno
    B7x(["No hay documento de Calc: sys.exit(1)"]):::uno
    B8["SheetAdmin (proteger / desproteger la hoja)"]:::uno
    B9["registrar_seguimiento_foco_calc<br/>· D1"]:::uno
    B10{"leer_modo()<br/>modo_sistema.json"}:::app

    A8 --> B1 --> B2
    B2 -- "no" --> B2x
    B2 -- "sí" --> B3 --> B4 --> B5
    B5 -- "no" --> B5x
    B5 -- "sí" --> B6
    B6 -.-> P1
    B6 --> B7
    B7 -- "no" --> B7x
    B7 -- "sí" --> B8 --> B9 --> B10

    %% Modo ventas_dia (solo lectura)
    V1["VentasService.obtener_ventas(fecha)"]:::app
    V2["attach_existing: tabla VENTAS DEL DÍA<br/>que horneó el prebake"]:::uno
    V3["SheetButtonBridge.activate<br/>botón REGRESAR AL SISTEMA PRINCIPAL<br/>· D3"]:::decidir
    V4(["vigilar_documento → ver diagrama 4"]):::uno

    B10 -- "ventas_dia" --> V1 --> V2 --> V3 --> V4

    %% Modo normal
    N1["VentasService, UsuariosService, CatalogoService,<br/>CodigosBarrasService + TableManager"]:::app
    N2["_registrar_usuario<br/>sincroniza con el SO y registra al actual"]:::app
    N2a["Aviso: no se pudo registrar tu usuario"]:::uno
    N3["SeguimientoSesionSistema<br/>(hilo de latido)"]:::app
    N4{"preparar_tablas<br/>¿hoja prehorneada y al día?"}:::uno
    N4a["attach_existing<br/>(se engancha a lo horneado)"]:::uno
    N4b["Reconstruye las tablas en vivo con UNO"]:::uno
    N5["AutocompletadoProductoHandler<br/>addKeyHandler (Tab → selector)"]:::uno
    N6["otorgar_plantilla_a_usuario_nuevo<br/>(solo si el usuario es nuevo)"]:::app
    N7["Contexto + cargar_acciones (acciones/*.py)"]:::app
    N8["ControladorVenta"]:::app
    N9["BotonesDeLaHoja.construir<br/>+ SheetButtonBridge.prepare / publish_layout / start<br/>on_tick = revisar_cambios · D3"]:::decidir
    N10["keyboard.add_hotkey('enter', on_enter)<br/>· D1"]:::decidir
    N11(["vigilar_documento → ver diagrama 4"]):::uno
    P2[["camera_viewer<br/>(botón VER CÁMARAS)"]]:::app
    P3[["admin_botones, Qt<br/>(botón ADMINISTRAR ADMINS, solo ADMIN_RAIZ)"]]:::app

    B10 -- "normal" --> N1 --> N2
    N2 -. "si falla" .-> N2a
    N2 --> N3 --> N4
    N4 -- "sí" --> N4a --> N5
    N4 -- "no" --> N4b --> N5
    N5 --> N6 --> N7 --> N8 --> N9 --> N10 --> N11
    N9 -.-> P2
    N9 -.-> P3

    classDef uno fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef dos fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef decidir fill:#ffedd5,stroke:#c2410c,color:#4a1d06,stroke-width:2px,stroke-dasharray:6 3
    classDef externo fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px
```

Notas:

- `open_system.sh`, el lock y el `Main` de Basic no tienen fila propia en la tabla de nodos del
  mapa; se marcan con **D5** (quién lanza a quién) porque esa decisión es la que los define.
  El borrado de `modo_sistema.json` se marca **App** porque el mapa pone `modo_sistema` en el
  lanzador de App.
- `camera_viewer` y `camera_viewer.archiver` son de la otra instancia: aquí solo se dibuja que se
  lanzan.

## 2. Flujo de Enter (`ControladorVenta`)

```mermaid
flowchart TD
    E0(["El usuario pulsa Enter<br/>(o el escáner lo manda al final del código)"]):::externo
    E1["Hook global de keyboard<br/>llama a on_enter en su propio hilo<br/>· D1"]:::decidir
    E2{"es_libreoffice_calc_enfocado<br/>¿Calc tiene el foco?"}:::uno
    E2x(["Ignora el Enter"]):::app
    E3{"¿autocompletado_handler.selector_activo?"}:::uno
    E3x(["Nada: el Enter es del selector"]):::app
    E4["enfocar_celda_sin_azul → B4"]:::uno
    E5{"¿ctx.selling?<br/>(venta en curso)"}:::app
    E5x(["Venta en curso, por favor espere"]):::app
    E6{"scanner_detector.is_scan()<br/>¿ritmo de escáner?<br/>· D1"}:::decidir

    E0 --> E1 --> E2
    E2 -- "no" --> E2x
    E2 -- "sí" --> E3
    E3 -- "sí" --> E3x
    E3 -- "no" --> E4 --> E5
    E5 -- "sí" --> E5x
    E5 -- "no" --> E6

    %% Escaneo
    S1["on_scan: get_scanned_string(clear=True)"]:::decidir
    S2{"¿Código vacío?"}:::app
    S2x(["No se procesa nada"]):::app
    S3{"CodigosBarrasService<br/>¿código registrado?"}:::app
    S4["Entrada = producto, precio, 1"]:::app
    S5["Selector de autocompletado<br/>seleccionar_producto()"]:::uno
    S6["Diálogo solicitar_precio_venta"]:::uno
    S7["registrar_codigo_barras<br/>(el producto NO se agrega al carrito)"]:::app
    S9(["Cancelado"]):::app

    E6 -- "sí" --> S1 --> S2
    S2 -- "sí" --> S2x
    S2 -- "no" --> S3
    S3 -- "sí" --> S4
    S3 -- "no" --> S5
    S5 -- "cancela" --> S9
    S5 -- "elige producto" --> S6
    S6 -- "cancela" --> S9
    S6 -- "precio" --> S7

    %% Agregar o cobrar
    C1{"add_item_to_cart<br/>¿fila de entrada completa?"}:::app
    C2["Suma al carrito (mismo producto y precio)<br/>o agrega fila; limpia la entrada"]:::app
    C2p["Pinta entrada y carrito en la hoja"]:::uno
    C3{"_cobrar: ¿existe acciones/cobrar_carrito.py?"}:::app
    C3x["registrar_evento_de_fallo<br/>FALLO AL COBRAR"]:::app
    C4["cobrar_carrito: selling = True<br/>sell_items(carrito, ventas)"]:::app
    C5{"¿Carrito vacío?"}:::app
    C6["Diálogo de cobro<br/>solicitar_monto_cliente(total)"]:::uno
    C6x(["Venta cancelada"]):::app
    C7["Agrega las filas a la tabla de ventas"]:::uno
    C8["registrar_venta en ventas.db"]:::app
    C9["imprimir_ticket_venta<br/>(un fallo solo se registra)"]:::app
    C10["Vacía el carrito · selling = False"]:::app

    E6 -- "no" --> C1
    S4 --> C1
    C1 -- "sí" --> C2 --> C2p
    C1 -- "no" --> C3
    C3 -- "no" --> C3x
    C3 -- "sí" --> C4 --> C5
    C5 -- "no" --> C6
    C6 -- "cancela" --> C6x
    C6 -- "monto" --> C7 --> C8 --> C9 --> C10

    %% Carrito vacío: código de apertura de caja
    K1["Devuelve code:<br/>diálogo solicitar_codigo"]:::uno
    K2{"¿Código == CODIGO_APERTURA_CAJA?"}:::app
    K2x(["No hace nada"]):::app
    K3["abrir_caja: TicketPrinter.open_cash_drawer"]:::app
    K4["registrar_evento APERTURA DE CAJA<br/>o FALLO AL ABRIR CAJA"]:::app
    K4p["Agrega la fila del evento a ventas"]:::uno

    C5 -- "sí" --> K1
    K1 -- "cancela" --> K2x
    K1 -- "código" --> K2
    K2 -- "no" --> K2x
    K2 -- "sí" --> K3 --> K4 --> K4p

    F1["finally: scanner_detector.clear_buffer()<br/>· D1"]:::decidir
    F2["Cualquier excepción: se registra<br/>FALLO INESPERADO y el hilo sigue vivo"]:::app
    E3x & E5x & S2x & S9 & S7 & C2p & C3x & C6x & C10 & K2x & K4p --> F1
    F1 -.-> F2

    classDef uno fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef dos fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef decidir fill:#ffedd5,stroke:#c2410c,color:#4a1d06,stroke-width:2px,stroke-dasharray:6 3
    classDef externo fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px
```

Notas:

- Los nodos de decisión de `ControladorVenta` son **App** (fila 22 del mapa); lo que hoy se le
  inyecta (foco, celda, diálogos, selector) es **UNO** y en la V3 serían mensajes a UNO.
- La comprobación del foco (E2) sobra si D1 se resuelve con `XKeyHandler` en UNO.
- El Enter con Calc sin foco sale antes del `try`, así que en ese caso no se ejecuta
  `clear_buffer()` (no está dibujado como flecha a F1 a propósito).

## 3. Clic en un botón de la hoja

```mermaid
flowchart TD
    subgraph Publicar["Al arrancar y cada vez que cambian los botones"]
        P1["BotonesDeLaHoja.construir<br/>lista de botones visibles del usuario"]:::app
        P2["SheetButtonBridge.publish_layout<br/>invoca macros Basic por script provider<br/>· D3"]:::decidir
        P3["Basic: TPV_PrepararComunicacionMacro,<br/>TPV_LimpiarBotonesMacro,<br/>TPV_CrearBotonMacro por cada botón<br/>· D3"]:::decidir
        P1 --> P2 --> P3
    end

    U0(["El usuario hace clic en un botón"]):::externo
    U1["Macro Basic TPV_ButtonAction<br/>saca el action_id del nombre del control<br/>· D3"]:::decidir
    U2["TPV_EscribirEvento: escribe NNNN_ticks.part<br/>y lo renombra a .evt en share/logs/events<br/>(línea CLICK con acción, etiqueta, usuario y hora)<br/>· D3"]:::decidir
    U3["TPV_RestaurarFocoCalc"]:::uno

    P3 --> U0 --> U1 --> U2 --> U3

    subgraph Sondeo["Hilo SheetButtonBridge, cada 0.5 s"]
        H1["_drain_events: *.evt en orden de nombre<br/>· D3"]:::decidir
        H2["Lee la línea y borra el archivo<br/>· D3"]:::decidir
        H3{"¿Es CLICK y hay handler<br/>para ese action_id?"}:::decidir
        H3x(["Click sin handler: solo log"]):::app
        H4["on_tick → BotonesDeLaHoja.revisar_cambios"]:::app
        H5{"¿Cambió el resumen de botones<br/>en la base?"}:::app
        H1 --> H2 --> H3
        H3 -- "no" --> H3x
    end

    U2 -. "archivo .evt" .-> H1

    A1["handler(): acción del botón"]:::app
    A2["ADMINISTRAR ADMINS → abrir_panel_admin"]:::app
    A3["boton_dinamico_ID → acciones/archivo.ejecutar(ctx)<br/>abrir_caja, cobrar_carrito, limpiar_carrito,<br/>autocompletado, imprimir / ver códigos, ver_ventas…"]:::app
    A3u["Diálogos y cambios en la hoja de la acción"]:::uno
    A4["ver_camaras"]:::app
    A5["Modo ventas_dia: regresar_sistema_principal<br/>escribir_modo normal + relanzar.flag"]:::app
    A5u["desktop.terminate()"]:::uno
    X1[["admin_botones, Qt (.venv)"]]:::app
    X2[["camera_viewer (.venv)"]]:::app

    H3 -- "sí" --> A1
    A1 --> A2 & A3 & A4 & A5
    A2 -.-> X1
    A4 -.-> X2
    A3 --> A3u
    A5 --> A5u

    H3x --> H4
    A1 --> H4
    H4 --> H5
    H5 -- "sí" --> P1
    H5 -- "no" --> H1

    classDef uno fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef dos fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef decidir fill:#ffedd5,stroke:#c2410c,color:#4a1d06,stroke-width:2px,stroke-dasharray:6 3
    classDef externo fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px
```

Notas:

- Todo el camino Basic → `.evt` → sondeo es **UNO** en el mapa, pero el mecanismo es D3; por eso
  va en naranja. Con D3 (b), `XActionListener`, desaparecen U1, U2, H1 y H2.
- En modo `ventas_dia` no hay `on_tick`: solo existe el botón REGRESAR.
- Los botones corren en el hilo de sondeo, no en el de `keyboard`: Enter y un clic pueden correr a
  la vez; lo único que los coordina es `ctx.selling`.

## 4. Cierre

```mermaid
flowchart TD
    W0(["El usuario cierra con X / Alt+F4,<br/>un botón cierra LibreOffice o soffice se cae"]):::externo
    W1["vigilar_documento: cada 1 s lee documento.Title<br/>y hace setModified(False)"]:::uno
    W2["La lectura lanza una excepción:<br/>se le avisa a quien decide"]:::uno
    W3{"resolver_salida_del_documento<br/>¿la excepción termina en<br/>UnknownPropertyException?"}:::app
    W4["Cierre normal:<br/>reiniciar_intentos_relanzamiento_por_fallo"]:::app
    W5{"registrar_intento_relanzamiento_por_fallo<br/>¿menos de 2 intentos en 600 s?"}:::app
    W6["solicitar_relanzamiento → relanzar.flag"]:::app
    W7["No se relanza (para no ciclar)"]:::app

    W0 --> W1 --> W2 --> W3
    W3 -- "sí" --> W4
    W3 -- "no (caída)" --> W5
    W5 -- "sí" --> W6
    W5 -- "no" --> W7

    M1{"¿Modo normal?"}:::app
    M2["SeguimientoSesionSistema.cerrar<br/>(exitosa = cierre normal)"]:::app
    M3["bridge.close<br/>· D3"]:::decidir
    M4["removeKeyHandler(autocompletado)"]:::uno
    M5["keyboard.unhook_all<br/>· D1"]:::decidir
    M6["terminar_libreoffice: desktop.terminate()<br/>(por orden de App)"]:::uno
    M7["atexit: detiene camera_viewer.archiver<br/>(terminate, 5 s, kill)"]:::app

    W4 & W6 & W7 --> M1
    M1 -- "sí" --> M2 --> M3 --> M4 --> M5 --> M6
    M1 -- "no (ventas_dia)" --> M3
    M6 --> M7

    L1["open_system.sh: termina soffice<br/>y el lanzador sale de la espera<br/>· D5"]:::decidir
    L2{"¿Existe relanzar.flag?<br/>· D5"}:::decidir
    L3["Borra el flag y vuelve al prebake<br/>sin borrar modo_sistema.json"]:::decidir
    L4(["Fin del sistema"]):::externo

    M6 --> L1 --> L2
    L2 -- "sí" --> L3
    L2 -- "no" --> L4

    classDef uno fill:#dbeafe,stroke:#1d4ed8,color:#0b1f4d,stroke-width:2px
    classDef app fill:#dcfce7,stroke:#15803d,color:#0b3d1c,stroke-width:2px
    classDef dos fill:#ede9fe,stroke:#6d28d9,color:#2e1065,stroke-width:2px
    classDef decidir fill:#ffedd5,stroke:#c2410c,color:#4a1d06,stroke-width:2px,stroke-dasharray:6 3
    classDef externo fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1px
```

Notas:

- `relanzar.flag` lo escriben tres caminos: el botón REGRESAR y `ver_ventas` (cambio de modo),
  la política de caídas (W6) y `asegurar_instancia_unica` al desplazar a otro usuario.
- En modo `ventas_dia` la salida no pasa por el seguimiento de sesión, el `removeKeyHandler` ni
  `keyboard.unhook_all`: esos no se llegan a crear en ese modo.

## Discrepancias encontradas

Diferencias entre `mapa_v2.md` y el código de `v_2` al 2026-09-29. No se corrigió el mapa.

> **Estado:** revisadas el mismo día. La 2, la 3 y la 4 se verificaron contra el código y ya
> están incorporadas en `mapa_v2.md`. La 1 no es un error: el `Module1` del repo difiere de la
> copia guardada dentro de `main.ods`, que es la que corre y lanza `/usr/bin/python3` (lo
> confirmó el usuario y se ve en el proceso vivo). El diagrama de arranque ya muestra esa ruta.

1. **Intérprete que lanza `Main` en Linux.** El mapa (sección 1) dice
   `sudo /usr/bin/python3 main.py`. En `libreofficeModules/Module1` esa línea está comentada; la
   que corre es `sudo /opt/python_global/bin/python /home/jesjack/sistema_ventas/v_2/main.py`.
2. **`gi` no se usa en el flujo real.** El mapa (tabla de paquetes, nodos 7 y 24, y D1) dice que
   el foco de Calc se comprueba con `gi` como plan B. Pero lo que se inyecta en
   `ControladorVenta` es `calc/calc_window_focus.es_libreoffice_calc_enfocado`, que solo usa UNO
   (`getActiveFrame().getContainerWindow().isActive()`) y devuelve `True` si algo falla. El plan B
   con `gi`/Wnck está en `calc/calc_focus.calc_esta_enfocado`, que nadie llama, y su `import gi`
   es local a la función, así que `main.py` no llega a importar `gi`. Por lo mismo, el estado que
   guarda `registrar_seguimiento_foco_calc` (nodo 7) solo lo lee esa función sin uso: hoy ese
   nodo no alimenta nada.
3. **`Main` de Basic hace más que lanzar Python.** Antes del `Shell` ejecuta
   `TPV_PrepararComunicacion` y `TPV_LimpiarBotones` (prepara la carpeta de eventos y borra los
   botones que hubiera en la hoja). El mapa solo menciona el lanzamiento; importa para D3 y D5.
4. **Pasos del lanzador que el mapa no lista.** En la primera vuelta del bucle, `open_system.sh`
   borra `modo_sistema.json` (por eso un arranque desde el ícono siempre entra en modo normal) y
   el lock de `main.ods` solo se borra si no hay ningún `soffice.bin` del mismo usuario. Tanto
   `open_system.sh` como `Main` usan rutas absolutas fijas (`/home/jesjack/sistema_ventas/v_2`,
   `C:\Users\jesjack\sistema_ventas\v_2`), algo a tener en cuenta con la meta de «misma
   instalación en Windows y Linux».

## Validación de la sintaxis Mermaid

No se validó con una herramienta: en este equipo no hay `node` ni `npx` (y por tanto tampoco
`@mermaid-js/mermaid-cli`), y la regla era no instalar nada global. Se escribió con cuidado para
evitar los tropiezos conocidos (todas las etiquetas entre comillas, sin `|` ni `#` dentro de
las etiquetas, identificadores de nodo sin palabras reservadas), pero conviene abrirlo en un
visor de Mermaid (GitHub, la vista previa de VS Code o mermaid.live) antes de darlo por bueno.
