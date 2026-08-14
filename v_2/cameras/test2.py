import re
import cv2
import requests
from requests.auth import HTTPDigestAuth

# 1. Configuración de acceso al DVR Dahua
IP_DVR = "192.168.1.108"
USUARIO = "nancy"
CONTRASENA = "2409"
CANAL = 1
FECHA_BUSQUEDA = "2026-07-30"  # Cambia esta fecha cuando gustes

AUTH = HTTPDigestAuth(USUARIO, CONTRASENA)

def obtener_clips_disponibles(fecha, canal):
    """Crea una sesión en el DVR, busca los clips y extrae sus rangos de tiempo."""
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
        
        # Consultamos los primeros 50 clips indexados
        url_results = f"http://{IP_DVR}/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={object_id}&count=50"
        res_results = requests.get(url_results, auth=AUTH)
        
        # Procesar la respuesta con expresiones regulares para agrupar los índices
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

def reproducir_clip(clip_inicio, clip_fin):
    """Conecta OpenCV al flujo HTTP del clip seleccionado."""
    # Codificar el espacio para la URL HTTP
    param_inicio = clip_inicio.replace(" ", "%20")
    param_fin = clip_fin.replace(" ", "%20")
    
    api_url = f"http://{USUARIO}:{CONTRASENA}@{IP_DVR}/cgi-bin/loadfile.cgi?action=startLoad&channel={CANAL}&startTime={param_inicio}&endTime={param_fin}"
    
    print(f"\n[+] Abriendo transmisión para el rango seleccionado...")
    cap = cv2.VideoCapture(api_url, cv2.CAP_FFMPEG)
    
    if not cap.isOpened():
        print("[-] Error: No se pudo decodificar el clip de video.")
        return

    print("[💡] Reproduciendo... Presiona 'q' para cerrar el video y volver al menú.")
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[+] Fin del fragmento de video.")
            break
            
        cv2.imshow('Visor de Grabaciones Internas - Dahua', frame)
        
        if cv2.waitKey(20) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

# --- FLUJO PRINCIPAL DEL PROGRAMA ---
if __name__ == "__main__":
    print(f"Buscando videos en el DVR para la fecha: {FECHA_BUSQUEDA}...")
    lista_clips = obtener_clips_disponibles(FECHA_BUSQUEDA, CANAL)
    
    if not lista_clips:
        print("[-] No se encontraron registros para procesar.")
        exit()
        
    print(f"\nSe encontraron {len(lista_clips)} clips de video disponibles:")
    for i, clip in enumerate(lista_clips):
        # Mostrar rango legible ej: "[0] 07:47:51 -> 08:50:51"
        hora_i = clip['inicio'].split(" ")[1]
        hora_f = clip['fin'].split(" ")[1]
        print(f" [{i}] {hora_i} ➔ {hora_f}")
        
    try:
        seleccion = int(input("\n👉 Selecciona el número de clip que deseas visualizar: "))
        if 0 <= seleccion < len(lista_clips):
            target = lista_clips[seleccion]
            reproducir_clip(target['inicio'], target['fin'])
        else:
            print("[-] Selección inválida.")
    except ValueError:
        print("[-] Entrada no válida. Debes ingresar un número.")
