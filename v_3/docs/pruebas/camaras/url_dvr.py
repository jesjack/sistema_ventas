"""Imprime la URL RTSP de un canal del DVR, leyendo las credenciales del .env de la v2 (no se muestran en el log)."""
import sys
sys.path.insert(0, '/home/jesjack/sistema_ventas/v_2')
from camera_viewer.dvr_credentials import dvr_credentials
from urllib.parse import quote
host, user, pw = dvr_credentials()
canal = sys.argv[1] if len(sys.argv) > 1 else '1'
sub = sys.argv[2] if len(sys.argv) > 2 else '1'
print(f"rtsp://{quote(user)}:{quote(pw, safe='')}@{host}:554/cam/realmonitor?channel={canal}&subtype={sub}")
