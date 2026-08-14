from datetime import datetime
import requests
from requests.auth import HTTPDigestAuth

IP_DVR = "192.168.1.108"
USUARIO = "nancy"
CONTRASENA = "2409"
AUTH = HTTPDigestAuth(USUARIO, CONTRASENA)

def sincronizar_firmware_antiguo():
    ahora_pc = datetime.now()
    
    # Los firmwares antiguos requerían la fecha unida por guiones y la hora por dos puntos
    # pero codificados en un formato plano sin acciones compuestas
    fecha_str = ahora_pc.strftime("%Y-%m-%d")
    hora_str = ahora_pc.strftime("%H:%M:%S")
    
    # Ruta CGI compatible con la era de los plugins ActiveX/NPAPI
    url_base = f"http://{IP_DVR}/cgi-bin/timeZone.cgi"
    
    parametros = {
        "action": "set",
        "date": fecha_str,
        "time": hora_str
    }
    
    print(f"[+] Hora de la PC: {fecha_str} {hora_str}")
    print("[+] Enviando comando clásico a timeZone.cgi...")
    
    try:
        respuesta = requests.get(url_base, auth=AUTH, params=parametros, timeout=10)
        
        if respuesta.status_code == 200 and "OK" in respuesta.text:
            print("  ¡Éxito! El firmware antiguo ha aceptado la hora.")
        else:
            # Si falla el primero, probamos la segunda ruta alternativa de esa época
            print("[-] Falló timeZone.cgi, intentando ruta alternativa de mantenimiento...")
            url_alt = f"http://{IP_DVR}/cgi-bin/sysinfo.cgi"
            params_alt = {"action": "setSystemTime", "time": ahora_pc.strftime("%Y%m%d%H%M%S")}
            
            res_alt = requests.get(url_alt, auth=AUTH, params=params_alt, timeout=10)
            if "OK" in res_alt.text:
                print("  ¡Éxito con ruta alternativa!")
            else:
                print(f"[-] Ambos métodos rechazados. Respuesta: {res_alt.text.strip()}")
                
    except Exception as e:
        print(f"[-] Error de red: {e}")

if __name__ == "__main__":
    sincronizar_firmware_antiguo()
