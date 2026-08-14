import time
import requests
from requests.auth import HTTPDigestAuth

# 1. Configuración de red y credenciales
ip_dvr = "192.168.1.108"
usuario = "nancy"
contrasena = "2409"
auth = HTTPDigestAuth(usuario, contrasena)

canal = 1
# Cambia esta fecha para auditar el día que desees investigar
fecha_busqueda = "2026-07-30" 

# 2. PASO 1: Crear un objeto/token de búsqueda en el DVR
url_create = f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=factory.create"
res_create = requests.get(url_create, auth=auth)

if "result" not in res_create.text:
    print("[-] No se pudo crear la sesión de búsqueda en el DVR.")
    exit()

# Extraer el ID de sesión asignado por el DVR
object_id = res_create.text.split("result=")[1].strip()
print(f"[+] Sesión de búsqueda creada con ID: {object_id}")

try:
    # 3. PASO 2: Enviar las condiciones (Buscar en todo el rango de ese día)
    start_time = f"{fecha_busqueda}%2000:00:00"
    end_time = f"{fecha_busqueda}%2023:59:59"
    
    url_find = (
        f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=findFile&object={object_id}"
        f"&condition.Channel={canal}&condition.StartTime={start_time}&condition.EndTime={end_time}"
    )
    requests.get(url_find, auth=auth)
    
    # 4. PASO 3: Solicitar y desplegar los fragmentos reales encontrados
    # Buscaremos hasta 50 fragmentos de video individuales guardados ese día
    url_results = f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={object_id}&count=50"
    res_results = requests.get(url_results, auth=auth)
    
    print(f"\n===== GRABACIONES ENCONTRADAS PARA EL {fecha_busqueda} =====")
    lines = res_results.text.split("\n")
    
    found = False
    for line in lines:
        # Filtrar las líneas que contienen los tiempos de inicio y fin de cada clip
        if "StartTime" in line or "EndTime" in line or "FileSize" in line:
            print(line.strip())
            found = True
            
    if not found:
        print("[-] No se encontraron fragmentos de video grabados en esta fecha.")

finally:
    # 5. PASO 4: Cerrar la sesión en el DVR para liberar memoria del disco
    url_close = f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=destroy&object={object_id}"
    requests.get(url_close, auth=auth)
    print("\n[+] Sesión de búsqueda cerrada correctamente.")
