import sys
import time
import statistics

try:
	import keyboard
except Exception:
	print("Este script requiere el paquete 'keyboard'. Instala con: pip install keyboard")
	sys.exit(1)


def is_printable_key(name: str) -> bool:
	# Considerar caracteres imprimibles más espacio y signos comunes
	if len(name) == 1:
		return True
	return name in ("space", "comma", "dot", "period", "minus", "slash", "semicolon", "quote")


timestamps = []


def on_key(event):
	# Usamos on_press (event_type implicitamente 'down')
	name = event.name
	now = time.perf_counter()

	# Ignorar teclas de edición
	if name in ("backspace", "delete", "shift", "ctrl", "alt", "caps lock"):
		return

	# Si se presiona Enter: mostrar resumen parcial y reiniciar medición
	if name == "enter":
		if len(timestamps) < 2:
			print("\nNo hay suficientes datos para calcular promedio en este segmento.")
		else:
			intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
			avg = statistics.mean(intervals)
			avg_ms = avg * 1000
			cps = 1 / avg if avg > 0 else float("inf")
			cpm = cps * 60
			wpm = cpm / 5
			is_scan = is_likely_scanner_segment(timestamps)
			print()
			print(f"Resumen parcial: teclas={len(timestamps)} | promedio={avg_ms:.1f} ms | {cps:.2f} cps | {wpm:.1f} WPM | scanner_probable={'SI' if is_scan else 'NO'}")
		# Reiniciar buffer para la siguiente lectura
		timestamps.clear()
		return

	# Registrar sólo teclas imprimibles y espacio
	if is_printable_key(name):
		timestamps.append(now)
		if len(timestamps) >= 2:
			intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
			avg = statistics.mean(intervals)
			avg_ms = avg * 1000
			cps = 1 / avg if avg > 0 else float("inf")
			cpm = cps * 60
			wpm = cpm / 5
			print(f"\rPromedio intervalo: {avg_ms:.1f} ms | {cps:.2f} cps | {wpm:.1f} WPM", end="", flush=True)


def summary_and_exit():
	keyboard.unhook_all()
	print()
	if len(timestamps) < 2:
		print("No hay datos suficientes para calcular promedios.")
		sys.exit(0)

	intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
	avg = statistics.mean(intervals)
	avg_ms = avg * 1000
	cps = 1 / avg if avg > 0 else float("inf")
	cpm = cps * 60
	wpm = cpm / 5

	print("Resumen:")
	print(f"Teclas registradas: {len(timestamps)}")
	print(f"Promedio intervalo entre caracteres: {avg_ms:.1f} ms")
	print(f"Caracteres por segundo: {cps:.2f}")
	print(f"Palabras por minuto (estimado): {wpm:.1f}")
	sys.exit(0)


def is_likely_scanner_segment(timestamps, *, min_length=3, max_avg_ms=20.0, max_allowed_gap_ms=60.0, max_std_ms=15.0):
	"""Determina si un segmento de timestamps proviene probablemente de un lector de códigos.

	Heurística basada en:
	- longitud mínima de caracteres
	- promedio de intervalo entre teclas (ms)
	- máximo intervalo permitido entre pulsaciones (ms)
	- desviación estándar de los intervalos (ms)
	"""
	if not timestamps or len(timestamps) < 2:
		return False
	if len(timestamps) < min_length:
		return False

	intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
	intervals_ms = [i * 1000.0 for i in intervals]
	avg_ms = statistics.mean(intervals_ms)
	max_gap = max(intervals_ms)
	std_ms = statistics.pstdev(intervals_ms) if len(intervals_ms) > 1 else 0.0

	# Condiciones: promedio rápido, sin gaps largos, y consistencia (std baja)
	if avg_ms <= max_avg_ms and max_gap <= max_allowed_gap_ms and std_ms <= max_std_ms:
		return True
	return False


def main():
	print("Empieza a escribir. Presiona ESC para finalizar y ver el resumen.")
	keyboard.on_press(on_key)
	# Bloquea hasta que se presione ESC
	try:
		keyboard.wait("esc")
	except KeyboardInterrupt:
		pass
	summary_and_exit()


if __name__ == "__main__":
	main()