import cv2

# 1. Parámetros de conexión de tu DVR Dahua
IP_DVR = "192.168.1.108"
USUARIO = "nancy"
CONTRASENA = "2409"
CANAL = 1  # Canal 1

# subtype=0 significa Stream Principal (Máxima resolución)
# subtype=1 significa Sub Stream (Baja resolución, ideal si la red va lenta)
URL_VIVO = f"rtsp://{USUARIO}:{CONTRASENA}@{IP_DVR}:554/cam/realmonitor?channel={CANAL}&subtype=0"

print(f"[+] Conectando a la cámara {CANAL} en vivo...")
print(f"[💡] Cargando transmisión...")

# 2. Inicializar la captura de video forzando el backend FFMPEG
cap = cv2.VideoCapture(URL_VIVO, cv2.CAP_FFMPEG)

if not cap.isOpened():
    print("[-] Error: No se pudo conectar a la transmisión en vivo del DVR.")
    exit()

print("[+] Éxito. Presiona 'q' para cerrar la ventana de video.")

while True:
    ret, frame = cap.read()
    
    if not ret:
        print("[-] Se perdió la conexión con el flujo de video.")
        break
        
    # 3. Mostrar el cuadro de video en pantalla
    cv2.imshow(f'Camara {CANAL} en Vivo - DVR Dahua', frame)
    
    # Detener la reproducción inmediatamente si el usuario presiona la tecla 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        print("[!] Transmisión cerrada por el usuario.")
        break

cap.release()
cv2.destroyAllWindows()
