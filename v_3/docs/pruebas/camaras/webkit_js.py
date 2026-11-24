"""Carga una página en WebKitGTK (sin ventana visible), espera N ms y evalúa una expresión JS.
Uso: python3 -I webkit_js.py <ruta_o_url> <js> [espera_ms] [png]"""
import sys, gi
gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib
destino, js = sys.argv[1], sys.argv[2]
espera = int(sys.argv[3]) if len(sys.argv) > 3 else 300
png = sys.argv[4] if len(sys.argv) > 4 else None
win = Gtk.Window(title="Prueba (se cierra sola)")  # visible: WebKit no carga video en ventanas invisibles; v = WebKit2.WebView(); win.add(v); win.set_default_size(800, 600); win.show_all()
v.get_settings().set_property('media-playback-requires-user-gesture', False)
def listo(view, ev):
    if ev == WebKit2.LoadEvent.FINISHED:
        GLib.timeout_add(espera, lambda: (view.evaluate_javascript(js, -1, None, None, None, fin, None), False)[1])
def fin(view, res, _):
    print(view.evaluate_javascript_finish(res).to_string())
    if png:
        view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, foto, None)
    else:
        Gtk.main_quit()
def foto(view, res, _):
    view.get_snapshot_finish(res).write_to_png(png); Gtk.main_quit()
v.connect('load-changed', listo)
v.load_uri(destino if '://' in destino else 'file://' + destino)
GLib.timeout_add(espera + 15000, Gtk.main_quit)
Gtk.main()
