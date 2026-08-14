import requests
from requests.auth import HTTPDigestAuth

IP_DVR = "192.168.1.108"
USUARIO = "nancy"
CONTRASENA = "2409"
AUTH = HTTPDigestAuth(USUARIO, CONTRASENA)

def consultar_hora_actual():
    # URL para consultar la configuración de tiempo actual del DVR
    url = f"http://{IP_DVR}/cgi-bin/configManager.cgi?action=getConfig&name=Time"
    
    try:
        r = requests.get(url, auth=AUTH, timeout=5)
        print("===== HORA INTERNA REPORTADA POR EL DVR =====")
        print(r.text.strip())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    consultar_hora_actual()
