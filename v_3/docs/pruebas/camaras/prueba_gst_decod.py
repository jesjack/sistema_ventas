"""Decodifica N cámaras del DVR por software (avdec_h264) sin mostrarlas y mide la CPU de gst-launch.
Uso: python3 prueba_gst_decod.py <num_camaras> <subtype> <segundos>"""
import os, subprocess, sys, time
AQUI = os.path.dirname(os.path.abspath(__file__))
N, SUB, SEG = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
HZ = os.sysconf('SC_CLK_TCK')
args = ['gst-launch-1.0', '-q']
for i in range(1, N + 1):
    url = subprocess.check_output([sys.executable, os.path.join(AQUI, 'url_dvr.py'), str(i), SUB], text=True).strip()
    args += ['rtspsrc', f'location={url}', 'protocols=tcp', 'latency=200', '!', 'rtph264depay', '!', 'avdec_h264', '!',
             'videoconvert', '!', 'fakesink', 'sync=true']
p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
def cpu():
    with open(f'/proc/{p.pid}/stat') as f:
        c = f.read().rsplit(')', 1)[1].split()
    return int(c[11]) + int(c[12])
time.sleep(4)
if p.poll() is not None:
    import re
    print('gst-launch terminó antes de medir:', re.sub(r'rtsp://[^@\s]*@', 'rtsp://***@', p.stderr.read().decode()[-400:]))
    sys.exit(1)
c0, t0 = cpu(), time.time()
time.sleep(SEG)
c1, t1 = cpu(), time.time()
p.terminate(); p.wait(5)
print(f'camaras={N} subtype={SUB} cpu={100 * (c1 - c0) / HZ / (t1 - t0):.1f}% (100% = un núcleo)')
