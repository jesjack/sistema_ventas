"""Prueba de cámaras, camino 1: RTSP del DVR → FFmpeg (solo reempaqueta, -c copy) → MP4
fragmentado por HTTP local → <video> en WebKitGTK. Mide CPU de FFmpeg y del proceso web.

Uso: python3 prueba_camaras_web.py <num_camaras> <subtype> <segundos> <png>
Las URLs (con credenciales) se piden a url_dvr.py y nunca se imprimen.
"""
import os, subprocess, sys, time, json
import gi
gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib

AQUI = os.path.dirname(os.path.abspath(__file__))
N, SUB, SEG, PNG = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
HZ = os.sysconf('SC_CLK_TCK')

def url(canal):
    return subprocess.check_output([sys.executable, os.path.join(AQUI, 'url_dvr.py'), str(canal), SUB], text=True).strip()

def cpu(pid):
    try:
        with open(f'/proc/{pid}/stat') as f:
            campos = f.read().rsplit(')', 1)[1].split()
        return int(campos[11]) + int(campos[12])  # utime + stime
    except OSError:
        return 0

def hijos(pid):
    try:
        return [int(p) for p in open(f'/proc/{pid}/task/{pid}/children').read().split()]
    except OSError:
        return []

def escuchando(puerto):
    salida = subprocess.run(['ss', '-ltnH', f'sport = :{puerto}'], capture_output=True, text=True).stdout
    return bool(salida.strip())

# Conexiones al DVR EN SERIE, como camera_viewer (dvr_client._open_capture_serialized): una a la
# vez, y 1.5 s de margen tras cada una. FFmpeg abre el RTSP antes de escuchar en el puerto local,
# así que "escuchando" = ya conectado al DVR.
ffmpegs = []
for i in range(N):
    puerto = 8091 + i
    f = subprocess.Popen(
        ['ffmpeg', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-i', url(i + 1), '-an', '-c:v', 'copy',
         '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-listen', '1',
         f'http://127.0.0.1:{puerto}/cam.mp4'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    ffmpegs.append(f)
    t = time.time()
    while time.time() - t < 15 and not escuchando(puerto) and f.poll() is None:
        time.sleep(0.1)
    print(f'cam {i + 1}: ' + (f'conectada en {time.time() - t:.1f}s' if escuchando(puerto) else 'NO conectó'), file=sys.stderr)
    if not escuchando(puerto):
        break
    time.sleep(1.5)
videos = ''.join(f'<video id="v{i}" autoplay muted playsinline src="http://127.0.0.1:{8091 + i}/cam.mp4"></video>' for i in range(N))
html = f"""<!doctype html><html><body style="margin:0;background:#111;display:grid;grid-template-columns:1fr 1fr;gap:4px">
<style>video{{width:100%;background:#000}}</style>{videos}</body></html>"""

win = Gtk.Window(title="Prueba de cámaras (se cierra sola)"); vista = WebKit2.WebView(); win.add(vista); win.set_default_size(960, 600); win.show_all()
ajustes = vista.get_settings(); ajustes.set_property('media-playback-requires-user-gesture', False)
resultado = {}

def estado(js_listo):
    js = "JSON.stringify([...document.querySelectorAll('video')].map(v=>({listo:v.readyState,t:+v.currentTime.toFixed(1),w:v.videoWidth,h:v.videoHeight,err:v.error&&v.error.code})))"
    vista.evaluate_javascript(js, -1, None, None, None, js_listo, None)

def medir_inicio():
    resultado['web'] = hijos(os.getpid())
    resultado['t0'] = time.time()
    resultado['c0'] = {p: cpu(p) for p in [f.pid for f in ffmpegs] + resultado['web']}
    GLib.timeout_add(SEG * 1000, medir_fin)
    return False

def medir_fin():
    dt = time.time() - resultado['t0']
    pct = {p: round(100 * (cpu(p) - c) / HZ / dt, 1) for p, c in resultado['c0'].items()}
    resultado['ffmpeg_%'] = [pct[f.pid] for f in ffmpegs]
    resultado['web_%'] = {open(f'/proc/{p}/comm').read().strip() if os.path.exists(f'/proc/{p}') else p: pct[p] for p in resultado['web']}
    def fin_estado(v, res, _):
        resultado['videos'] = json.loads(vista.evaluate_javascript_finish(res).to_string())
        vista.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, fin_foto, None)
    estado(fin_estado)
    return False

def fin_foto(v, res, _):
    vista.get_snapshot_finish(res).write_to_png(PNG)
    Gtk.main_quit()

vista.load_html(html, 'http://127.0.0.1/')
GLib.timeout_add(5000, medir_inicio)
GLib.timeout_add((SEG + 20) * 1000, Gtk.main_quit)
Gtk.main()
for f in ffmpegs:
    f.terminate()
for f in ffmpegs:
    try:
        f.wait(5)
    except subprocess.TimeoutExpired:
        f.kill()
errores = [f.stderr.read().decode(errors='replace')[-300:] for f in ffmpegs]
resultado.pop('c0', None); resultado.pop('t0', None); resultado.pop('web', None)
import re
resultado['errores_ffmpeg'] = [re.sub(r'rtsp://[^@\s]*@', 'rtsp://***@', e).replace('\n', ' ') for e in errores if e.strip()]
print(json.dumps(resultado, ensure_ascii=False))
