import sys
import time
import os
import uno
from pynput import mouse, keyboard

# --- 1. CONEXIÓN REMOTA A LIBREOFFICE VÍA UNO (SOCKETS) ---
def conectar_a_calc():
    try:
        # Conectarse al puerto 2002 que abrió el archivo .sh
        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_context
        )
        ctx = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
        
        # Obtener el objeto del documento activo
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.getCurrentComponent()
        
        # Devolvemos tanto el contexto como el documento para poder usar el Toolkit gráfico
        return ctx, doc
    except Exception as e:
        # Guardar registro de error si Calc no responde en el puerto
        with open(os.path.expanduser("~/error_conexion.txt"), "w") as f:
            f.write(f"No se pudo conectar al puerto 2002: {str(e)}")
        sys.exit(1)

# --- 2. FUNCIÓN PARA MOSTRAR EL MODAL EMERGENTE ---
def mostrar_modal_confirmacion(ctx, doc):
    try:
        # Acceder al Toolkit de Calc para crear ventanas de interfaz gráfica
        smgr = ctx.ServiceManager
        toolkit = smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        
        # Buscar la ventana activa actual de LibreOffice Calc
        frame = doc.getCurrentController().getFrame()
        ventana_padre = frame.getContainerWindow()
        
        # Importar constantes de la API de LibreOffice para el estilo de la ventana
        from com.sun.star.awt.MessageBoxType import MESSAGEBOX
        from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
        
        # Crear la estructura de la ventana emergente
        msgbox = toolkit.createMessageBox(
            ventana_padre, 
            MESSAGEBOX, 
            BUTTONS_OK, 
            "Conexión Exitosa", 
            "¡El script de Python se ha conectado correctamente en el puerto 2002!"
        )
        msgbox.execute() # Hacer que aparezca en pantalla
        msgbox.dispose() # Liberar memoria al darle Aceptar
    except Exception as e:
        with open(os.path.expanduser("~/error_modal.txt"), "w") as f:
            f.write(f"No se pudo mostrar el modal: {str(e)}")

# --- 3. INICIALIZACIÓN Y OBTENCIÓN DE DATOS DE CALC ---
ctx, doc = conectar_a_calc()
hoja = doc.Sheets.getByName("TPV")
celda_b3 = hoja.getCellRangeByName("B3")

# Coordenadas métricas internas de Calc
pos_b3 = celda_b3.Position 
tam_b3 = celda_b3.Size

# --- 4. PRUEBA DE ÉXITO (ARCHIVO Y MODAL) ---
with open(os.path.expanduser("~/script_funcionando.txt"), "w") as f:
    f.write(f"¡Conectado exitosamente vía puerto 2002!\n")
    f.write(f"Geometría de B3 -> X: {pos_b3.X}, Y: {pos_b3.Y}, Ancho: {tam_b3.Width}\n")

# Lanzar el modal visual en LibreOffice
mostrar_modal_confirmacion(ctx, doc)


# --- 5. LÓGICA DE MONITOREO DE PERIFÉRICOS (pynput) ---
celda_b3_seleccionada = False
ultimo_click_time = 0

def al_detectar_edicion(motivo):
    """Acción en tiempo real cuando se edita B3"""
    print(f"⚠️ Alerta: Edición en B3 detectada por {motivo}")
    # Ejemplo de manipulación remota:
    # celda_b3.setString("Modificado por Python")

def on_click(x, y, button, pressed):
    global ultimo_click_time, celda_b3_seleccionada
    if pressed and button == mouse.Button.left:
        ahora = time.time()
        
        try:
            seleccion = doc.getCurrentSelection()
            if seleccion.supportsService("com.sun.star.sheet.SheetCell"):
                if seleccion.CellAddress.Column == 1 and seleccion.CellAddress.Row == 2: # Columna B, Fila 3
                    celda_b3_seleccionada = True
                    if ahora - ultimo_click_time < 0.35:
                        al_detectar_edicion("Doble Clic")
                else:
                    celda_b3_seleccionada = False
        except:
            pass
        ultimo_click_time = ahora

def on_press(key):
    global celda_b3_seleccionada
    if celda_b3_seleccionada:
        try:
            if key == keyboard.Key.f2:
                al_detectar_edicion("Tecla F2")
            elif hasattr(key, 'char') and key.char is not None:
                al_detectar_edicion(f"Escritura directa de: {key.char}")
        except:
            pass

# Iniciar los escuchadores globales de pynput
mouse_listener = mouse.Listener(on_click=on_click)
keyboard_listener = keyboard.Listener(on_press=on_press)
mouse_listener.start()
keyboard_listener.start()
mouse_listener.join()
keyboard_listener.join()

