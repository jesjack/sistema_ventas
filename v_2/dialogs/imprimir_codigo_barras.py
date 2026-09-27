from dialogs._base import ConstructorDialogo, EscuchaTexto
from dialogs.formato import TEXTO_INICIAL, TEXTO_SIN_CONSULTA, describir_codigo
from dialogs.parseo import parse_copias


def _crear_dialogo(uno_context, error_texto="", codigo="", copias="1"):
    c = ConstructorDialogo(uno_context, "Imprimir código de barras", 250, 178)
    c.etiqueta("lblInstruccion", 8, 8, 234, 12, "Ingrese el texto del código y la cantidad de copias.")
    c.etiqueta("lblTexto", 8, 26, 92, 12, "Código (máx. 6):")
    c.campo("txtCodigo", 104, 24, 134, 14, texto=codigo, max_len=6)
    c.etiqueta("lblCopias", 8, 46, 92, 12, "Copias (1 a 5):")
    c.campo("txtCopias", 104, 44, 40, 14, texto=copias, max_len=1)
    # Se rellena mientras se escribe el código (ver _enlazar_informacion).
    c.etiqueta("lblInfo", 8, 66, 234, 62, TEXTO_INICIAL, multilinea=True)
    c.etiqueta("lblError", 8, 130, 234, 22, error_texto, multilinea=True)
    c.aceptar_cancelar(156, x_aceptar=148, x_cancelar=198)
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


def solicitar_datos_codigo_barras(uno_context, buscar_codigo=None):
    """Pide el código y las copias. `buscar_codigo(codigo)` devuelve el CodigoBarras registrado (o
    None); con él, el diálogo muestra el producto y el precio mientras se escribe."""
    error_texto = ""
    codigo_previo, copias_previas = "", "1"

    while True:
        dialog = _crear_dialogo(uno_context, error_texto, codigo_previo, copias_previas)
        escucha = _enlazar_informacion(dialog, buscar_codigo) if buscar_codigo is not None else None
        try:
            result = dialog.execute()
            if result != 1:
                return None

            texto = dialog.getControl("txtCodigo").getModel().Text
            copias_texto = dialog.getControl("txtCopias").getModel().Text
        finally:
            dialog.dispose()
            del escucha

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

        return codigo, copias
