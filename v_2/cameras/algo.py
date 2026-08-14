import requests
from requests.auth import HTTPDigestAuth

# Configuración del DVR
IP_DVR = "192.168.1.108"
USUARIO = "nancy"
CONTRASENA = "2409"
AUTH = HTTPDigestAuth(USUARIO, CONTRASENA)

# LA IP DE TU COMPUTADORA (según tu ifconfig)
IP_MI_PC = "192.168.1.20"

def activar_ntp_servidor_local():
    print(f"[+] Configurando el DVR para que busque la hora en tu PC ({IP_MI_PC})...")
    
    # Ruta universal para firmwares antiguos de Dahua (Módulo de Zona Horaria y NTP)
    url_api = f"http://{IP_DVR}/cgi-bin/timeZone.cgi"
    
    parametros = {
        "action": "set",
        "ntpEnable": "true",          # Activar cliente NTP
        "ntpServer": IP_MI_PC,        # Apuntar a tu Linux
        "ntpPort": "123",             # Puerto estándar NTP
        "ntpInterval": "1"            # Sincronizar muy seguido (Cada minuto)
    }
    
    try:
        respuesta = requests.get(url_api, auth=AUTH, params=parametros, timeout=10)
        
        if respuesta.status_code == 200 and "OK" in respuesta.text:
            print("  ¡Éxito! El DVR ha guardado la IP de tu PC como su servidor de hora.")
            
            # COMANDO EXTRA: Forzar actualización inmediata de reloj por hardware
            print("[+] Forzando al DVR a actualizar el tiempo justo ahora...")
            url_update = f"http://{IP_DVR}/cgi-bin/timeZone.cgi?action=update"
            requests.get(url_update, auth=AUTH, timeout=5)
            print("  Calibración completada. Revisa la vista en vivo.")
            
        else:
            # Intento alternativo si el firmware es de la era de transición
            print("[-] timeZone.cgi dio error o no existe. Intentando ruta alternativa...")
            url_alt = f"http://{IP_DVR}/cgi-bin/configManager.cgi"
            params_alt = {
                "action": "setConfig",
                "NTP.Enable": "true",
                "NTP.Address": IP_MI_PC,
                "NTP.Port": "123",
                "NTP.UpdatePeriod": "1"
            }
            res_alt = requests.get(url_alt, auth=AUTH, params=params_alt, timeout=10)
            if "OK" in res_alt.text:
                print("  ¡Éxito con la ruta alternativa de red!")
            else:
                print(f"[-] El DVR rechazó ambos comandos. Respuesta final:\n{res_alt.text.strip()}")
                
    except Exception as e:
        print(f"[-] Error de red al comunicar con el DVR: {e}")

if __name__ == "__main__":
    activar_ntp_servidor_local()
