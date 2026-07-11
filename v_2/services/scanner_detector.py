import statistics
import threading
import time


MAX_AVG_MS = 20.0
MAX_ALLOWED_GAP_MS = 60.0
MAX_STD_MS = 15.0
MIN_LENGTH = 3


timestamps = []
scanned_chars = []
_lock = threading.Lock()
_keyboard = None
_hook_handle = None
_listener_started = False


def _reset_history_for_new_segment(timestamp):
	"""Arranca un nuevo tramo de lectura y descarta el historial previo."""
	timestamps[:] = [timestamp]
	scanned_chars.clear()


def record_key(timestamp=None):
	"""Registra la pulsacion actual para evaluar luego si vino de un scanner."""
	if timestamp is None:
		timestamp = time.perf_counter()
	with _lock:
		if timestamps and (timestamp - timestamps[-1]) * 1000.0 > MAX_ALLOWED_GAP_MS:
			_reset_history_for_new_segment(timestamp)
			return
		timestamps.append(timestamp)


def clear_buffer():
	"""Limpia las ultimas pulsaciones registradas."""
	with _lock:
		timestamps.clear()
		scanned_chars.clear()


def get_scanned_string(clear=False):
	"""Devuelve el texto acumulado en el tramo actual como string."""
	with _lock:
		text = "".join(scanned_chars)
		if clear:
			timestamps.clear()
			scanned_chars.clear()
		return text


def is_scan():
	"""Devuelve True si las ultimas teclas registradas parecen venir de un scanner."""
	with _lock:
		if len(timestamps) < MIN_LENGTH:
			return False

		intervals_ms = [
			(timestamps[i] - timestamps[i - 1]) * 1000.0
			for i in range(1, len(timestamps))
		]
		avg_ms = statistics.mean(intervals_ms)
		max_gap_ms = max(intervals_ms)
		std_ms = statistics.pstdev(intervals_ms) if len(intervals_ms) > 1 else 0.0

		return (
			avg_ms <= MAX_AVG_MS
			and max_gap_ms <= MAX_ALLOWED_GAP_MS
			and std_ms <= MAX_STD_MS
		)


def _is_printable_key(name):
	return len(name) == 1 or name in ("space", "comma", "dot", "period", "minus", "slash", "semicolon", "quote")


def _key_to_char(name):
	if len(name) == 1:
		return name
	if name == "space":
		return " "
	if name in ("comma",):
		return ","
	if name in ("dot", "period"):
		return "."
	if name == "minus":
		return "-"
	if name == "slash":
		return "/"
	if name == "semicolon":
		return ";"
	if name == "quote":
		return "'"
	return ""


def _on_key(event):
	if getattr(event, "event_type", None) != "down":
		return
	name = getattr(event, "name", None)
	if not name:
		return
	if _is_printable_key(name):
		record_key(getattr(event, "time", None))
		char = _key_to_char(name)
		if char:
			with _lock:
				scanned_chars.append(char)


def start_listener():
	"""Activa la captura global de teclas sin bloquear el hilo principal."""
	global _keyboard, _hook_handle, _listener_started
	if _listener_started:
		return True

	try:
		import keyboard as _keyboard_module
	except Exception:
		return False

	try:
		_keyboard = _keyboard_module
		_hook_handle = _keyboard.hook(_on_key)
		_listener_started = True
		return True
	except Exception:
		_keyboard = None
		_hook_handle = None
		_listener_started = False
		return False


def stop_listener():
	"""Detiene la captura global si estaba activa."""
	global _hook_handle, _listener_started
	if _keyboard is None or _hook_handle is None:
		return
	try:
		_keyboard.unhook(_hook_handle)
	finally:
		_hook_handle = None
		_listener_started = False


def main():
	if not start_listener():
		print("Este script requiere el paquete 'keyboard'. Instala con: pip install keyboard")
		return

	print("Escuchando en segundo plano. Usa is_scan() cuando necesites consultar el tramo actual.")
	print("Usa get_scanned_string() para obtener el contenido como texto.")
	print("La deteccion usa los umbrales:")
	print(f"- max_avg_ms={MAX_AVG_MS}")
	print(f"- max_allowed_gap_ms={MAX_ALLOWED_GAP_MS}")
	print(f"- max_std_ms={MAX_STD_MS}")

	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		stop_listener()
		clear_buffer()


if __name__ == "__main__":
	main()


start_listener()