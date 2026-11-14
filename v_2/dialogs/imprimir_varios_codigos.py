"""Imprimir varios códigos en las mismas etiquetas (3 piezas por etiqueta, siempre en vertical) y
registrar en el mismo paso los que son nuevos, con su producto y su precio."""

from dialogs._base import ACEPTAR, CANCELAR, ConstructorDialogo, EscuchaAccion, EscuchaTexto
from dialogs.formato import formatear_precio
from dialogs.imprimir_codigo_barras import _ultima_configuracion
from dialogs.seleccionar_codigo import seleccionar_codigo
from dialogs.seleccionar_producto import seleccionar_producto
from dialogs.varios_codigos import (
    MAX_LARGO_CODIGO,
    ListaPiezas,
    Renglon,
    leer_piezas,
    leer_precio,
    texto_faltantes,
    textos_renglones,
    texto_resumen,
    validar_codigo_escrito,
)
from services.catalogo_service import formatear_nombre

ANCHO, ALTO = 300, 278
TEXTO_CODIGO_NUEVO = "Código nuevo: elija el producto y el precio; se registrará al imprimir."
TEXTO_CODIGO_EN_LISTA = "Ya está en la lista: se le sumarán las piezas."
TEXTO_CODIGO_REGISTRADO = "Código ya registrado: el producto y el precio no se pueden cambiar."
TEXTO_BORRADOR = "Se recuperó lo que quedó escrito la última vez (aún sin imprimir)."

# Lo escrito en el diálogo se conserva al cerrarlo (mientras el sistema siga abierto), por si hay
# que atender otra cosa a mitad de la lista. Se descarta cuando los códigos quedan registrados
# para imprimirse (ver descartar_borrador) o con "Vaciar lista".
_borrador = {}


def descartar_borrador():
    _borrador.clear()


def _crear_dialogo(uno_context, codificadores, codificador):
    c = ConstructorDialogo(uno_context, "Imprimir varios códigos", ANCHO, ALTO, x=100, y=40)
    c.etiqueta(
        "lblInstruccion", 8, 6, 284, 20,
        "Agregue cada código con su producto, su precio y cuántas piezas imprimir. "
        "Caben 3 piezas por etiqueta, aunque sean de códigos distintos.",
        multilinea=True,
    )
    c.etiqueta("lblCodigo", 8, 32, 50, 12, f"Código (máx. {MAX_LARGO_CODIGO}):")
    c.campo("txtCodigo", 62, 30, 70, 14, max_len=MAX_LARGO_CODIGO)
    c.boton("btnElegirCodigo", 136, 30, 56, 14, "Elegir...")
    c.etiqueta("lblPiezas", 196, 32, 34, 12, "Piezas:")
    c.campo("txtPiezas", 232, 30, 60, 14, texto="1", max_len=2)
    c.etiqueta("lblProducto", 8, 50, 50, 12, "Producto:")
    c.campo("txtProducto", 62, 48, 170, 14, ReadOnly=True)
    c.boton("btnElegir", 236, 48, 56, 14, "Elegir...")
    c.etiqueta("lblPrecio", 8, 68, 50, 12, "Precio:")
    c.campo("txtPrecio", 62, 66, 70, 14)
    c.etiqueta("lblEstado", 8, 84, 200, 20, TEXTO_CODIGO_NUEVO, multilinea=True)
    c.boton("btnAgregar", 212, 86, 80, 14, "Agregar a la lista", por_defecto=True)
    # Letra de ancho fijo para que las columnas de textos_renglones() queden alineadas (LibreOffice
    # trae Liberation Mono también en Windows).
    c.agregar("lista", "lstRenglones", 8, 106, 284, 76, Dropdown=False, FontName="Liberation Mono")
    c.boton("btnQuitar", 8, 186, 80, 14, "Quitar seleccionado")
    c.boton("btnVaciar", 92, 186, 56, 14, "Vaciar lista")
    c.etiqueta("lblResumen", 154, 186, 138, 22, texto_resumen(ListaPiezas()), multilinea=True)
    c.etiqueta("lblCodificador", 8, 214, 50, 12, "Codificador:")
    indice = codificadores.index(codificador) if codificador in codificadores else 0
    c.agregar(
        "lista", "lstCodificador", 62, 212, 120, 14,
        Dropdown=True, StringItemList=tuple(codificadores), SelectedItems=(indice,),
    )
    c.etiqueta("lblError", 8, 232, 284, 20, "", multilinea=True, TextColor=0xB00000)
    c.boton("btnImprimir", 186, 258, 56, 14, "Imprimir")
    c.boton("btnCancel", 246, 258, 46, 14, "Cancelar", CANCELAR)
    return c.crear()


def _confirmar(uno_context, titulo, mensaje, texto_no, texto_si):
    """True si se elige `texto_si`; el botón por defecto (Enter) es `texto_no`."""
    c = ConstructorDialogo(uno_context, titulo, 230, 78, x=140, y=120)
    c.etiqueta("lblAviso", 8, 8, 214, 38, mensaje, multilinea=True)
    c.boton("btnNo", 8, 56, 100, 14, texto_no, CANCELAR, por_defecto=True)
    c.boton("btnSi", 152, 56, 70, 14, texto_si, ACEPTAR)
    dialog = c.crear()
    try:
        return dialog.execute() == 1
    finally:
        dialog.dispose()


def _confirmar_faltantes(uno_context, faltantes):
    """Aviso de que la última etiqueta no se llena. True si se imprime así."""
    return _confirmar(
        uno_context, "Faltan piezas",
        f"{texto_faltantes(faltantes)} Esos espacios saldrán en blanco: puede seguir añadiendo "
        "prendas a la lista para aprovechar la etiqueta.",
        "Seguir añadiendo", "Imprimir así",
    )


def solicitar_varios_codigos(
    uno_context, codificadores, catalogo, buscar_codigo, validar_codigo=None, listar_codigos=None
):
    """Arma la lista y devuelve (ListaPiezas, codificador), o None si se cancela. Lo escrito se
    conserva para la próxima vez hasta que se llame a descartar_borrador().

    - `catalogo`: CatalogoService, para elegir el producto (o registrarlo ahí mismo).
    - `buscar_codigo(codigo)`: el CodigoBarras registrado (o None); si lo está, su producto y su
      precio quedan fijos.
    - `validar_codigo(codigo, codificador)`: lanza ValueError si el codificador no acepta el código.
    - `listar_codigos(filtro)`: los CodigoBarras registrados, para elegir uno que ya existe.
    """
    codificadores = list(codificadores)
    codificador_inicial = (
        _borrador.get("codificador") or _ultima_configuracion["codificador"] or codificadores[0]
    )
    dialog = _crear_dialogo(uno_context, codificadores, codificador_inicial)
    control = dialog.getControl
    lista = _borrador.get("lista") or ListaPiezas()
    # producto: (id, nombre) elegido; bloqueado: el producto y el precio vienen de un código ya
    # registrado o ya en la lista y no se editan.
    estado = {"producto": None, "bloqueado": False, "registrado": False, "resultado": None}

    def texto(nombre):
        return str(control(nombre).getModel().Text)

    def avisar(mensaje):
        control("lblError").getModel().Label = mensaje

    def codificador_actual():
        seleccion = control("lstCodificador").getModel().SelectedItems
        return codificadores[seleccion[0]] if seleccion else codificadores[0]

    def poner_producto(producto):
        estado["producto"] = producto
        control("txtProducto").getModel().Text = formatear_nombre(producto[1]) if producto else ""

    def bloquear(bloqueado):
        estado["bloqueado"] = bloqueado
        # Solo lectura y no deshabilitados: deshabilitados, el texto se ve casi blanco y no se lee.
        control("txtPrecio").getModel().ReadOnly = bloqueado

    def al_cambiar_codigo():
        codigo = texto("txtCodigo").strip()
        en_lista = lista.buscar(codigo) if codigo else None
        registrado = None
        if codigo and en_lista is None:
            try:
                registrado = buscar_codigo(codigo)
            except Exception as exc:
                print(f"No se pudo consultar el código '{codigo}': {exc}")

        conocido = en_lista or registrado
        if conocido is not None:
            if en_lista is not None:
                producto, precio = (en_lista.producto_id, en_lista.producto), en_lista.precio
                mensaje = TEXTO_CODIGO_EN_LISTA
            else:
                producto, precio = (registrado.producto_id, registrado.producto), registrado.precio_venta
                mensaje = TEXTO_CODIGO_REGISTRADO
            poner_producto(producto)
            control("txtPrecio").getModel().Text = formatear_precio(precio).lstrip("$")
            bloquear(True)
            estado["registrado"] = en_lista.registrado if en_lista is not None else True
            control("lblEstado").getModel().Label = mensaje
            return

        if estado["bloqueado"]:
            # Lo que había venía del código anterior: no es de este.
            poner_producto(None)
            control("txtPrecio").getModel().Text = ""
            bloquear(False)
        estado["registrado"] = False
        control("lblEstado").getModel().Label = TEXTO_CODIGO_NUEVO

    def refrescar_lista(seleccionar=None):
        control("lstRenglones").getModel().StringItemList = tuple(textos_renglones(lista.renglones))
        if seleccionar is not None:
            control("lstRenglones").selectItemPos(seleccionar, True)
        control("lblResumen").getModel().Label = texto_resumen(lista)

    def elegir():
        if estado["bloqueado"]:
            avisar("El producto de este código ya está fijo; para otro producto use otro código.")
            return
        producto = seleccionar_producto(uno_context, catalogo)
        if producto is not None:
            poner_producto(producto)
            avisar("")
            control("txtPrecio").setFocus()

    def elegir_codigo():
        if listar_codigos is None:
            return
        codigo = seleccionar_codigo(uno_context, listar_codigos)
        if codigo is not None:
            control("txtCodigo").getModel().Text = codigo
            al_cambiar_codigo()
            avisar("")
            control("txtPiezas").setFocus()

    def agregar():
        try:
            codigo = validar_codigo_escrito(texto("txtCodigo"), codificador_actual(), validar_codigo)
            piezas = leer_piezas(texto("txtPiezas"))
            if estado["producto"] is None:
                raise ValueError("Elija el producto (botón \"Elegir...\").")
            precio = leer_precio(texto("txtPrecio"))
        except ValueError as exc:
            avisar(str(exc))
            return

        producto_id, producto = estado["producto"]
        lista.agregar(Renglon(codigo, producto_id, producto, precio, piezas, registrado=estado["registrado"]))
        indice = lista.renglones.index(lista.buscar(codigo))
        refrescar_lista(seleccionar=indice)
        avisar("")
        control("txtCodigo").getModel().Text = ""
        control("txtPiezas").getModel().Text = "1"
        poner_producto(None)
        control("txtPrecio").getModel().Text = ""
        al_cambiar_codigo()
        control("txtCodigo").setFocus()

    def quitar():
        indice = int(control("lstRenglones").getSelectedItemPos())
        if not 0 <= indice < len(lista.renglones):
            avisar("Seleccione en la lista el renglón que quiere quitar.")
            return
        lista.quitar(indice)
        refrescar_lista(seleccionar=min(indice, len(lista.renglones) - 1) if lista.renglones else None)
        avisar("")
        al_cambiar_codigo()  # por si el código escrito era el que se quitó

    def vaciar():
        if not _confirmar(
            uno_context, "Vaciar lista",
            "¿Borrar toda la lista y lo escrito en los campos? Los códigos aún no se han registrado.",
            "No, conservar", "Sí, vaciar",
        ):
            return
        lista.renglones.clear()
        refrescar_lista()
        control("txtCodigo").getModel().Text = ""
        control("txtPiezas").getModel().Text = "1"
        poner_producto(None)
        control("txtPrecio").getModel().Text = ""
        avisar("")
        al_cambiar_codigo()
        control("txtCodigo").setFocus()

    def guardar_borrador():
        _borrador.update(
            lista=lista,
            codigo=texto("txtCodigo"),
            piezas=texto("txtPiezas"),
            producto=None if estado["bloqueado"] else estado["producto"],
            precio="" if estado["bloqueado"] else texto("txtPrecio"),
            codificador=codificador_actual(),
        )

    def imprimir():
        if not lista.renglones:
            avisar("Agregue al menos un código a la lista.")
            return
        codificador = codificador_actual()
        for renglon in lista.renglones:
            try:
                validar_codigo_escrito(renglon.codigo, codificador, validar_codigo)
            except ValueError as exc:
                avisar(str(exc))
                return
        if lista.faltantes and not _confirmar_faltantes(uno_context, lista.faltantes):
            return
        estado["resultado"] = (lista, codificador)
        dialog.endDialog(1)

    # Se conservan mientras el diálogo esté abierto.
    escuchas = {
        "txtCodigo": EscuchaTexto(al_cambiar_codigo),
        "btnElegir": EscuchaAccion(elegir),
        "btnElegirCodigo": EscuchaAccion(elegir_codigo),
        "btnAgregar": EscuchaAccion(agregar),
        "btnQuitar": EscuchaAccion(quitar),
        "btnVaciar": EscuchaAccion(vaciar),
        "btnImprimir": EscuchaAccion(imprimir),
    }
    control("txtCodigo").addTextListener(escuchas["txtCodigo"])
    for nombre in ("btnElegir", "btnElegirCodigo", "btnAgregar", "btnQuitar", "btnVaciar", "btnImprimir"):
        control(nombre).addActionListener(escuchas[nombre])

    if _borrador:
        # El producto y el precio antes que el código: si el código ya está registrado (o en la
        # lista), al_cambiar_codigo pone los suyos encima.
        poner_producto(_borrador["producto"])
        control("txtPrecio").getModel().Text = _borrador["precio"]
        control("txtPiezas").getModel().Text = _borrador["piezas"]
        control("txtCodigo").getModel().Text = _borrador["codigo"]
        refrescar_lista()
        if lista.renglones or _borrador["codigo"].strip() or _borrador["producto"]:
            avisar(TEXTO_BORRADOR)
    al_cambiar_codigo()

    control("txtCodigo").setFocus()
    try:
        dialog.execute()
    finally:
        # Se lee antes de dispose(): después ya no hay controles.
        guardar_borrador()
        dialog.dispose()
        del escuchas

    if estado["resultado"] is not None:
        _ultima_configuracion["codificador"] = estado["resultado"][1]
    return estado["resultado"]
