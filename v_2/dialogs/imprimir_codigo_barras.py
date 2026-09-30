from dialogs._base import ConstructorDialogo, EscuchaAccion, EscuchaTexto
from dialogs.formato import TEXTO_INICIAL, TEXTO_SIN_CONSULTA, describir_codigo
from dialogs.parseo import parse_copias

# La orientación y el codificador se recuerdan entre impresiones mientras el sistema siga abierto:
# lo normal es imprimir varias etiquetas seguidas con la misma configuración.
_ultima_configuracion = {"horizontal": False, "codificador": None}


def _crear_dialogo(uno_context, codificadores, error_texto="", codigo="", copias="1", horizontal=False,
                   codificador=None, con_prueba=False):
    c = ConstructorDialogo(uno_context, "Imprimir código de barras", 250, 214)
    c.etiqueta("lblInstruccion", 8, 8, 234, 12, "Ingrese el texto del código y la cantidad de copias.")
    c.etiqueta("lblTexto", 8, 26, 92, 12, "Código (máx. 6):")
    c.campo("txtCodigo", 104, 24, 134, 14, texto=codigo, max_len=6)
    c.etiqueta("lblCopias", 8, 46, 92, 12, "Copias (1 a 5):")
    c.campo("txtCopias", 104, 44, 40, 14, texto=copias, max_len=1)
    c.etiqueta("lblCodificador", 8, 66, 92, 12, "Codificador:")
    indice = codificadores.index(codificador) if codificador in codificadores else 0
    c.agregar(
        "lista", "lstCodificador", 104, 64, 134, 14,
        Dropdown=True, StringItemList=tuple(codificadores), SelectedItems=(indice,),
    )
    c.casilla("chkHorizontal", 8, 84, 234, 12, "Imprimir el código en horizontal", marcada=horizontal)
    # Se rellena mientras se escribe el código (ver _enlazar_informacion).
    c.etiqueta("lblInfo", 8, 102, 234, 62, TEXTO_INICIAL, multilinea=True)
    c.etiqueta("lblError", 8, 166, 234, 22, error_texto, multilinea=True)
    if con_prueba:
        c.boton("btnPrueba", 8, 192, 110, 14, "Imprimir prueba de márgenes")
    c.aceptar_cancelar(192, x_aceptar=148, x_cancelar=198)
    return c.crear()


def _enlazar_informacion(dialog, buscar_codigo):
    """Cada vez que cambia el texto del código, muestra a qué producto pertenece (si ya está
    registrado). Devuelve el listener: hay que conservarlo mientras el diálogo esté abierto."""
    campo = dialog.getControl("txtCodigo")
    info = dialog.getControl("lblInfo").getModel()

    def actualizar():
        codigo = str(campo.getModel().Text).strip()
        if not codigo:
            info.Label = TEXTO_INICIAL
            return
        try:
            info.Label = describir_codigo(buscar_codigo(codigo))
        except Exception as exc:
            # Consultar es solo una ayuda: si la base falla, se puede imprimir igual.
            print(f"No se pudo consultar el código '{codigo}': {exc}")
            info.Label = TEXTO_SIN_CONSULTA

    escucha = EscuchaTexto(actualizar)
    campo.addTextListener(escucha)
    actualizar()  # por si el diálogo se reabre con un código ya escrito
    return escucha


def _enlazar_prueba(dialog, imprimir_prueba):
    """El botón de prueba imprime el marco sin cerrar el diálogo. Devuelve el listener."""
    aviso = dialog.getControl("lblError").getModel()

    def imprimir():
        try:
            imprimir_prueba()
            aviso.Label = "Prueba de márgenes enviada a la impresora."
        except Exception as exc:
            print(f"No se pudo imprimir la prueba de márgenes: {exc}")
            aviso.Label = f"No se pudo imprimir la prueba: {exc}"

    escucha = EscuchaAccion(imprimir)
    dialog.getControl("btnPrueba").addActionListener(escucha)
    return escucha


def solicitar_datos_codigo_barras(uno_context, codificadores, buscar_codigo=None, validar_codigo=None,
                                  imprimir_prueba=None):
    """Pide el código, las copias, el codificador y si va en horizontal. Devuelve
    (codigo, copias, horizontal, codificador) o None si se cancela.

    - `codificadores`: nombres a mostrar en la lista (el primero es el predeterminado).
    - `buscar_codigo(codigo)`: el CodigoBarras registrado (o None); con él, el diálogo muestra el
      producto y el precio mientras se escribe.
    - `validar_codigo(codigo, codificador)`: lanza ValueError si el codificador no acepta el código.
    - `imprimir_prueba()`: si se da, aparece el botón que imprime el marco de prueba de márgenes.
    """
    codificadores = list(codificadores)
    error_texto = ""
    codigo_previo, copias_previas = "", "1"
    horizontal = _ultima_configuracion["horizontal"]
    codificador = _ultima_configuracion["codificador"] or codificadores[0]

    while True:
        dialog = _crear_dialogo(
            uno_context, codificadores, error_texto, codigo_previo, copias_previas, horizontal, codificador,
            con_prueba=imprimir_prueba is not None,
        )
        escucha = _enlazar_informacion(dialog, buscar_codigo) if buscar_codigo is not None else None
        escucha_prueba = _enlazar_prueba(dialog, imprimir_prueba) if imprimir_prueba is not None else None
        try:
            result = dialog.execute()
            if result != 1:
                return None

            texto = dialog.getControl("txtCodigo").getModel().Text
            copias_texto = dialog.getControl("txtCopias").getModel().Text
            horizontal = dialog.getControl("chkHorizontal").getModel().State == 1
            seleccion = dialog.getControl("lstCodificador").getModel().SelectedItems
            codificador = codificadores[seleccion[0]] if seleccion else codificadores[0]
        finally:
            dialog.dispose()
            del escucha, escucha_prueba

        codigo = str(texto).strip()
        codigo_previo, copias_previas = codigo, str(copias_texto)
        if not codigo:
            error_texto = "El código no puede estar vacío."
            continue

        if len(codigo) > 6:
            error_texto = "El código debe tener como máximo 6 caracteres."
            continue

        try:
            copias = parse_copias(copias_texto)
        except (TypeError, ValueError):
            error_texto = "La cantidad de copias debe ser un número entero entre 1 y 5."
            continue

        if copias < 1 or copias > 5:
            error_texto = "La cantidad de copias debe estar entre 1 y 5."
            continue

        if validar_codigo is not None:
            try:
                validar_codigo(codigo, codificador)
            except ValueError as exc:
                error_texto = str(exc)
                continue

        _ultima_configuracion.update(horizontal=horizontal, codificador=codificador)
        return codigo, copias, horizontal, codificador
