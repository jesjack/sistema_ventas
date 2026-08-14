import re
import cv2
import requests
from requests.auth import HTTPDigestAuth
from ultralytics import YOLO

# 1. Configuración de acceso al DVR Dahua y Parámetros
IP_DVR = "192.168.1.108"
USUARIO = "nancy"
CONTRASENA = "2409"
CANAL = 3
FECHA_BUSQUEDA = "2026-07-30"  # Fecha de los clips que mapeaste

AUTH = HTTPDigestAuth(USUARIO, CONTRASENA)

# 2. Cargar el modelo de IA (YOLOv8 Nano: rápido y eficiente para CPU/GPU)
print("[+] Cargando modelo de Inteligencia Artificial...")
model = YOLO("yolov8s.pt") 


def obtener_clips_disponibles(fecha, canal):
    """Conecta al DVR, lee el mapa del disco y devuelve los segmentos reales."""
    url_create = f"http://{IP_DVR}/cgi-bin/mediaFileFind.cgi?action=factory.create"
    res_create = requests.get(url_create, auth=AUTH)
    
    if "result" not in res_create.text:
        print("[-] Error: No se pudo iniciar la sesión de búsqueda en el DVR.")
        return []
        
    object_id = res_create.text.split("result=")[1].strip()
    clips = []
    
    try:
        start_time = f"{fecha}%2000:00:00"
        end_time = f"{fecha}%2023:59:59"
        
        url_find = (
            f"http://{IP_DVR}/cgi-bin/mediaFileFind.cgi?action=findFile&object={object_id}"
            f"&condition.Channel={canal}&condition.StartTime={start_time}&condition.EndTime={end_time}"
        )
        requests.get(url_find, auth=AUTH)
        
        url_results = f"http://{IP_DVR}/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={object_id}&count=50"
        res_results = requests.get(url_results, auth=AUTH)
        
        data = res_results.text
        matches_start = re.findall(r"items\[(\d+)\].StartTime=(.+)", data)
        matches_end = re.findall(r"items\[(\d+)\].EndTime=(.+)", data)
        
        starts = {idx: val.strip() for idx, val in matches_start}
        ends = {idx: val.strip() for idx, val in matches_end}
        
        for idx in sorted(starts.keys(), key=int):
            if idx in ends:
                clips.append({"inicio": starts[idx], "fin": ends[idx]})
                
    finally:
        url_close = f"http://{IP_DVR}/cgi-bin/mediaFileFind.cgi?action=destroy&object={object_id}"
        requests.get(url_close, auth=AUTH)
        
    return clips


def analizar_clip_con_ia(clip_inicio, clip_fin):
    """Transmite el fragmento de video seleccionado y le aplica la IA cuadro por cuadro."""
    param_inicio = clip_inicio.replace(" ", "%20")
    param_fin = clip_fin.replace(" ", "%20")
    
    # URL HTTP con credenciales embebidas para OpenCV + FFmpeg
    api_url = f"http://{USUARIO}:{CONTRASENA}@{IP_DVR}/cgi-bin/loadfile.cgi?action=startLoad&channel={CANAL}&startTime={param_inicio}&endTime={param_fin}"
    
    print(f"\n[+] Conectando al segmento seleccionado...")
    cap = cv2.VideoCapture(api_url, cv2.CAP_FFMPEG)
    
    if not cap.isOpened():
        print("[-] Error: No se pudo abrir el flujo multimedia del DVR.")
        return

    print("[🚀] IA Iniciada. Presiona 'q' para detener el análisis y volver al menú.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[+] Fin del fragmento de video analizado.")
            break
            
        # Pasar el cuadro por la red neuronal de YOLO
        results = model(frame, stream=True, conf=0.50, classes=[0], verbose=False)
        
        # Dibujar las detecciones (personas, objetos, etc.) sobre el cuadro original
        frame_analizado = frame
        for r in results:
            frame_analizado = r.plot()
            
        # Mostrar el resultado final con las etiquetas de la IA
        cv2.imshow('Analisis de Grabacion con IA (YOLOv8)', frame_analizado)
        
        # Mantiene el video fluido (~20ms por cuadro)
        if cv2.waitKey(20) & 0xFF == ord('q'):
            print("[!] Análisis cancelado por el usuario.")
            break
            
    cap.release()
    cv2.destroyAllWindows()


# --- FLUJO PRINCIPAL ---
if __name__ == "__main__":
    print(f"Buscando videos disponibles en el DVR para el: {FECHA_BUSQUEDA}...")
    lista_clips = obtener_clips_disponibles(FECHA_BUSQUEDA, CANAL)
    
    if not lista_clips:
        print("[-] No se encontraron grabaciones válidas en esa fecha.")
        exit()
        
    print(f"\nSe encontraron {len(lista_clips)} clips de video en el disco:")
    for i, clip in enumerate(lista_clips):
        # Limpiar la fecha para mostrar solo las horas en el menú
        hora_i = clip['inicio'].split(" ")[1]
        hora_f = clip['fin'].split(" ")[1]
        print(f" [{i}] Bloque: {hora_i} ➔ {hora_f}")
        
    try:
        seleccion = int(input("\n👉 Elige el número de clip que deseas analizar con IA: "))
        if 0 <= seleccion < len(lista_clips):
            target = lista_clips[seleccion]
            analizar_clip_con_ia(target['inicio'], target['fin'])
        else:
            print("[-] Número fuera de rango.")
    except ValueError:
        print("[-] Entrada inválida. Debes ingresar un número entero.")
