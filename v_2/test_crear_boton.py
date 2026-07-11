""" import uno
from com.sun.star.uno import Exception as UnoException

def ejecutar_macro_basic():
    # 1. Conectar con la instancia de LibreOffice
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    
    try:
        context = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
        smgr = context.ServiceManager
        
        # 2. Obtener el escritorio (Desktop) para acceder a los documentos
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", context)
        doc = desktop.getCurrentComponent() # Obtiene el documento activo
        
        if not doc:
            print("No hay ningún documento activo abierto.")
            return

        # 3. Acceder al proveedor de scripts
        script_provider = doc.getScriptProvider()
        
        # 4. Definir la URI de la macro Basic
        # Formato: macro://[Origen]/[Librería].[Módulo].[NombreMacro]
        macro_uri = "vnd.sun.star.script:Standard.Module1.HelloWorld?language=Basic&location=document"
        
        # 5. Obtener y ejecutar la macro
        script = script_provider.getScript(macro_uri)
        
        # Los argumentos deben pasarse como una tupla (vacía si no lleva)
        argumentos = () 
        resultado, out_params, out_indices = script.invoke(argumentos, (), ())
        
        print("Macro ejecutada con éxito. Resultado:", resultado)

    except UnoException as e:
        print("Error de UNO:", e.Message)
    except Exception as e:
        print("Error de conexión:", e)

if __name__ == "__main__":
    ejecutar_macro_basic()
 """

import uno
from com.sun.star.uno import Exception as UnoException

def invocar_funcion_basic():
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    
    try:
        # Conexión al socket activo
        context = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
        desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
        doc = desktop.getCurrentComponent()
        
        if not doc:
            print("Por favor, abre un documento en LibreOffice primero.")
            return

        # 1. Localizar la función usando el protocolo interno de LibreOffice
        script_provider = doc.getScriptProvider()
        
        # CORRECCIÓN: Protocolo 'vnd.sun.star.script:' apuntando a 'location=document'
        macro_uri = "vnd.sun.star.script:Standard.Module1.CalcularPrecioTotal?language=Basic&location=document"
        script = script_provider.getScript(macro_uri)
        
        # 2. Definir los parámetros que enviaremos (precioBase=100.0, impuesto=0.16)
        parametros = (100.0, 0.16)
        
        # 3. Invocar la función pasando los parámetros en la tupla
        resultado, out_params, out_indices = script.invoke(parametros, (), ())
        
        # 4. Mostrar el valor retornado por la función Basic
        print("Respuesta recibida desde Basic:", resultado)
        # Me funcionó: Respuesta recibida desde Basic: El precio total con impuestos es: $116

    except UnoException as e:
        print("Error de UNO:", e.Message)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    invocar_funcion_basic()
