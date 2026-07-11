import sys
import uno
from time import sleep as wait

def conectar_y_verificar_foco(ctx):
    try:
        print("Iniciando verificación directa desde LibreOffice...")
        print("Tiene 3 segundos para cambiar de ventana y enfocarse en LibreOffice Calc...")
        wait(3)
        
        # 1. Conectar con el Administrador de Servicios
        smgr = ctx.ServiceManager
        
        # 2. Crear la instancia del Desktop
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        
        # 3. Obtener el Frame (marco) que LibreOffice considera activo internamente
        frame_activo = desktop.getActiveFrame()
        
        if not frame_activo:
            print("\n[RESULTADO] LibreOffice está abierto, pero no hay ningún documento cargado.")
            return False
            
        # 4. Obtener el contenedor de la ventana física (Window) del Frame
        ventana_componente = frame_activo.getContainerWindow()
        
        # 5. ¡LA CLAVE! Preguntar si esta ventana tiene el FOCO REAL del sistema operativo actualmente
        tiene_el_foco_real = ventana_componente.isActive()
        
        titulo_documento = frame_activo.getTitle()
        
        if tiene_el_foco_real:
            print(f"\n[ÉXITO] El usuario está enfocado REALMENTE en LibreOffice: '{titulo_documento}'")
            return True
        else:
            print(f"\n[CANCELADO] El documento '{titulo_documento}' está abierto, pero NO tiene el foco actual de la pantalla.")
            return False
            
    except Exception as e:
        print(f"\nError de comunicación con LibreOffice: {e}")
        print("Asegúrate de haber iniciado LibreOffice desde la terminal con el parámetro --accept")
        return False

if __name__ == "__main__":
    # Suponiendo que ya tienes configurado tu objeto 'ctx' de conexión remota por socket:
    try:
        contexto_local = uno.getComponentContext()
        resolver = contexto_local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", contexto_local
        )
        # Reemplaza con tu string de conexión si usas un puerto diferente
        ctx_remoto = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
        
        # Ejecutar la validación
        if conectar_y_verificar_foco(ctx_remoto):
            print("Procediendo a limpiar la fila 5 de la tabla...")
            # -> AQUÍ COLOCAS TU CÓDIGO DE MANIPULACIÓN DE CELDAS <-
        else:
            print("Operación abortada por falta de foco.")
            sys.exit(0)
            
    except Exception as e:
        print(f"No se pudo establecer la conexión inicial UNO: {e}")
        sys.exit(1)
