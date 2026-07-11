import uno

def crear_boton_hola_mundo():
    # 1. Conexión al puerto 2002 de LibreOffice
    contexto_local = uno.getComponentContext()
    resolver = contexto_local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", contexto_local
    )
    
    try:
        contexto_remoto = resolver.resolve(
            "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"
        )
        gestor_servicios = contexto_remoto.ServiceManager
    except Exception as e:
        print(f"Error: {e}")
        return

    # 2. Localizar el documento Calc abierto
    escritorio = gestor_servicios.createInstanceWithContext(
        "com.sun.star.frame.Desktop", contexto_remoto
    )
    documento = None
    components = escritorio.getComponents().createEnumeration()
    while components.hasMoreElements():
        comp = components.nextElement()
        if hasattr(comp, "getSheets"): 
            documento = comp
            break
            
    if not documento:
        documento = escritorio.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())

    # 3. Preparar hoja y controles
    hoja = documento.getSheets().getByIndex(0)
    
    # Crear modelo y forma gráfica
    modelo_boton = gestor_servicios.createInstanceWithContext(
        "com.sun.star.form.component.CommandButton", contexto_remoto
    )
    modelo_boton.Label = "Presióname"
    modelo_boton.Name = "BotonHolaMundo"

    forma_control = documento.createInstance("com.sun.star.drawing.ControlShape")
    
    # Configurar dimensiones y posición
    tamano = uno.createUnoStruct("com.sun.star.awt.Size")
    tamano.Width = 3000
    tamano.Height = 1000
    forma_control.setSize(tamano)
    
    # SOLUCIÓN CRÍTICA: Enlazar modelo a forma y añadir a la página de dibujo
    forma_control.setControl(modelo_boton)
    hoja.getDrawPage().add(forma_control)

    # 4. Registrar el control en el formulario
    formularios = hoja.getDrawPage().getForms()
    if formularios.getCount() == 0:
        formulario = gestor_servicios.createInstanceWithContext(
            "com.sun.star.form.component.Form", contexto_remoto
        )
        formularios.insertByIndex(0, formulario)
    else:
        formulario = formularios.getByIndex(0)

    formulario.insertByName("BotonHolaMundo", modelo_boton)
    print("Botón creado con éxito.")

if __name__ == "__main__":
    crear_boton_hola_mundo()
