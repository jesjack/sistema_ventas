from datetime import datetime, timedelta
import cv2

# 1. Configuración dinámica de la fecha de ayer
ayer = datetime.now() - timedelta(days=1)
fecha_formateada = ayer.strftime("%Y-%m-%d")

# 2. Rango de tiempo deseado
hora_inicio = "08:00:00"
hora_fin = "09:00:00"

param_inicio = f"{fecha_formateada}%20{hora_inicio}"
param_fin = f"{fecha_formateada}%20{hora_fin}"

# 3. Credenciales de acceso del DVR
ip_dvr = "192.168.1.108"
usuario = "nancy"
contrasena = "2409"
canal = 1  # Cámara 1

# 4. Construcción de la URL HTTP de Dahua con autenticación integrada para OpenCV
# Estructura: http://usuario:contraseña@IP/...
api_url = f"http://{usuario}:{contrasena}@{ip_dvr}/cgi-bin/loadfile.cgi?action=startLoad&channel={canal}&startTime={param_inicio}&endTime={param_fin}"

print(f"Conectando al flujo de descarga del DVR...")
print(f"URL de streaming: http://{usuario}:****@{ip_dvr}/cgi-bin/loadfile.cgi...")

# 5. Pasamos la URL directamente a VideoCapture. 
# Forzamos el backend FFMPEG para que decodifique el buffer binario en tiempo real.
cap = cv2.VideoCapture(api_url, cv2.CAP_FFMPEG)

if not cap.isOpened():
    print("[-] Error: No se pudo conectar al flujo del DVR o no hay grabaciones en ese horario.")
    exit()

print("[+] Conexión establecida. Abriendo reproductor...")

while True:
    ret, frame = cap.read()
    
    if not ret:
        print("[+] Fin de la grabación o buffer terminado.")
        break
        
    # Mostrar el cuadro en pantalla inmediatamente a medida que llega por red
    cv2.imshow('Reproducción Directa DVR (Ayer)', frame)
    
    # Control de velocidad de reproducción (25ms estándar para video fluido)
    # Presiona 'q' para salir en cualquier momento
    if cv2.waitKey(25) & 0xFF == ord('q'):
        print("[!] Reproducción detenida por el usuario.")
        break

cap.release()
cv2.destroyAllWindows()
