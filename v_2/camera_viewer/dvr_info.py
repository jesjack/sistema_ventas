from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

# Información técnica y de conectividad del DVR (botón "Información del
# DVR", ver dvr_info_dialog.py). Este módulo NO usa Qt: recibe un "fetcher"
# (consultas al DVR) y un "sampler" (muestra de video) y devuelve secciones
# de texto, para poder probarse sin conexión con respuestas reales guardadas
# (tests/fixtures/dvr_info/).
#
# Cada dato lleva una etiqueta de origen:
#   [DVR]        lo dice el propio equipo
#   [Medido]     lo medimos desde este equipo (ping, puertos, muestra de video)
#   [Calculado]  se deduce de otros datos
#   [Inferido]   suposición razonable, no confirmada por el DVR
#
# Solo consultas de LECTURA; nunca se piden las configuraciones de usuarios,
# claves, DDNS ni correo.

TAG_DVR = "DVR"
TAG_MEASURED = "Medido"
TAG_CALC = "Calculado"
TAG_INFERRED = "Inferido"
NOT_AVAILABLE = "no disponible"

CHANNELS = (1, 2, 3, 4)
QUERY_PAUSE = 0.15  # pausa entre consultas al DVR: van una por una
SAMPLE_SECONDS = 5
SAMPLE_AGE = timedelta(minutes=10)  # la muestra se toma de un clip ya cerrado
FIRMWARE_OLD_YEARS = 5
CLOCK_TOLERANCE = 2.0  # segundos de desfase que aún se consideran sincronizados
COVERAGE_GAP_SECONDS = 2  # un salto mayor entre clips seguidos cuenta como hueco
RECORDING_NOW_SECONDS = 120
DVR_PORTS = ((80, "HTTP"), (554, "RTSP"), (37777, "datos Dahua"))
EPOCH = datetime(2000, 1, 1)


class InfoCancelled(Exception):
    pass


class Fetcher(Protocol):
    def get(self, path: str) -> str: ...

    def find(self, channel: int, start: datetime, end: datetime) -> list[dict[str, str]]: ...


class Sampler(Protocol):
    def sample(self, channel: int, start: datetime, end: datetime) -> "StreamSample | None": ...


@dataclass
class StreamSample:
    width: int
    height: int
    fps: float
    codec: str
    kbps: float


@dataclass
class Row:
    label: str
    value: str
    tag: str = ""


@dataclass
class Section:
    title: str
    rows: list[Row] = field(default_factory=list)

    def add(self, label: str, value: str, tag: str = "") -> None:
        self.rows.append(Row(label, value, tag))


# -- parseo de respuestas -----------------------------------------------------


def parse_kv(text: str) -> dict[str, str]:
    """`table.Network.eth0.IPAddress=1.2.3.4` -> {"Network.eth0.IPAddress": "1.2.3.4"}
    (se quita el prefijo table./list.; las respuestas de magicBox no lo traen)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.strip().partition("=")
        for prefix in ("table.", "list."):
            if key.startswith(prefix):
                key = key[len(prefix) :]
        values[key] = value.strip()
    return values


def parse_time(text: str) -> datetime | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") if match else None


def parse_ping(output: str) -> dict[str, float | int | None]:
    """Resumen de `ping` (salida en inglés, LC_ALL=C): pérdida, min/avg/max/mdev en ms y TTL."""
    result: dict[str, float | int | None] = {"loss": None, "min": None, "avg": None, "max": None, "mdev": None, "ttl": None}
    loss = re.search(r"([\d.]+)% packet loss", output)
    if loss:
        result["loss"] = float(loss.group(1))
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", output)
    if rtt:
        result["min"], result["avg"], result["max"], result["mdev"] = (float(v) for v in rtt.groups())
    ttl = re.search(r"ttl=(\d+)", output)
    if ttl:
        result["ttl"] = int(ttl.group(1))
    return result


def hops_from_ttl(ttl: int) -> int:
    """Saltos estimados: los equipos salen con TTL 64, 128 o 255."""
    initial = next(value for value in (64, 128, 255) if ttl <= value)
    return initial - ttl


def parse_route(output: str) -> tuple[str | None, str | None]:
    """`ip -o route get X` -> (interfaz, IP de este equipo)."""
    dev = re.search(r"\bdev (\S+)", output)
    src = re.search(r"\bsrc (\S+)", output)
    return (dev.group(1) if dev else None, src.group(1) if src else None)


def fmt_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(count) < 1024 or unit == "TB":
            return f"{count:.1f} {unit}" if unit != "B" else f"{count:.0f} B"
        count /= 1024
    return f"{count:.1f} TB"


def fmt_duration_days(days: float) -> str:
    return f"{days:.1f} días"


# -- mediciones desde este equipo -------------------------------------------


def _run(command: list[str], timeout: float) -> str:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env={"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/bin"}
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def measure_connectivity(host: str) -> dict:
    """Ping al DVR y a la puerta de enlace, puertos abiertos y datos de la
    interfaz de red de este equipo. Corre en paralelo a las consultas al DVR
    (no abre sesiones en el DVR más allá de un connect TCP por puerto)."""
    ip = host.split(":")[0]
    route = _run(["ip", "-o", "route", "get", ip], 3)
    interface, local_ip = parse_route(route)
    gateway_match = re.search(r"\bvia (\S+)", route)
    speed = None
    if interface:
        try:
            speed = int(Path(f"/sys/class/net/{interface}/speed").read_text().strip())
        except (OSError, ValueError):
            speed = None
    ports = {}
    for port, _ in DVR_PORTS:
        started = time.monotonic()
        try:
            with socket.create_connection((ip, port), timeout=2):
                ports[port] = (True, (time.monotonic() - started) * 1000)
        except OSError:
            ports[port] = (False, None)
    return {
        "interface": interface,
        "local_ip": local_ip,
        "link_mbps": speed if speed and speed > 0 else None,
        "ping": parse_ping(_run(["ping", "-c", "8", "-i", "0.2", "-W", "2", ip], 10)),
        "gateway": gateway_match.group(1) if gateway_match else None,
        "ports": ports,
    }


def measure_gateway_ping(gateway: str) -> dict:
    return parse_ping(_run(["ping", "-c", "4", "-i", "0.2", "-W", "2", gateway], 6))


# -- recolección --------------------------------------------------------------


@dataclass
class Raw:
    """Todo lo obtenido, tal cual: None = ese paso falló."""

    text: dict[str, str | None] = field(default_factory=dict)
    clock: tuple[datetime, datetime] | None = None  # (PC antes, PC después) de pedir la hora
    oldest: dict[int, list[dict[str, str]] | None] = field(default_factory=dict)
    today: dict[int, list[dict[str, str]] | None] = field(default_factory=dict)
    samples: dict[int, StreamSample | None] | None = None  # None = no se intentó (modo en vivo)
    connectivity: dict | None = None
    gateway_ping: dict | None = None
    latencies: list[float] = field(default_factory=list)  # duración de cada consulta CGI


TEXT_STEPS: list[tuple[str, str, str]] = [
    # (grupo para la barra de progreso, clave, ruta CGI)
    ("Identificando el equipo", "sysinfo", "cgi-bin/magicBox.cgi?action=getSystemInfo"),
    ("Identificando el equipo", "name", "cgi-bin/magicBox.cgi?action=getMachineName"),
    ("Identificando el equipo", "type", "cgi-bin/magicBox.cgi?action=getDeviceType"),
    ("Identificando el equipo", "class", "cgi-bin/magicBox.cgi?action=getDeviceClass"),
    ("Identificando el equipo", "software", "cgi-bin/magicBox.cgi?action=getSoftwareVersion"),
    ("Identificando el equipo", "hardware", "cgi-bin/magicBox.cgi?action=getHardwareVersion"),
    ("Identificando el equipo", "vendor", "cgi-bin/magicBox.cgi?action=getVendor"),
    ("Consultando la hora", "time", "cgi-bin/global.cgi?action=getCurrentTime"),
    ("Consultando la hora", "locales", "cgi-bin/configManager.cgi?action=getConfig&name=Locales"),
    ("Consultando la red", "network", "cgi-bin/configManager.cgi?action=getConfig&name=Network"),
    ("Consultando la red", "ntp", "cgi-bin/configManager.cgi?action=getConfig&name=NTP"),
    ("Consultando los canales", "titles", "cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle"),
    ("Consultando los canales", "encode", "cgi-bin/configManager.cgi?action=getConfig&name=Encode"),
    ("Consultando los canales", "recordmode", "cgi-bin/configManager.cgi?action=getConfig&name=RecordMode"),
    ("Consultando el almacenamiento", "storage", "cgi-bin/storageDevice.cgi?action=getDeviceAllInfo"),
]


def total_steps(with_samples: bool) -> int:
    return len(TEXT_STEPS) + 2 * len(CHANNELS) + 1 + (len(CHANNELS) if with_samples else 0)


def collect(
    host: str,
    fetcher: Fetcher,
    sampler: Sampler | None,
    progress: Callable[[int, int, str], None],
    stop: threading.Event,
    now_fn: Callable[[], datetime] = datetime.now,
) -> Raw:
    """Ejecuta todos los pasos, uno tras otro (nunca dos consultas al DVR a
    la vez). Un paso que falla queda en None y se sigue. `sampler=None` =
    no tomar muestras de video (modo en vivo: no se mezclan descargas con el
    video en vivo)."""
    raw = Raw()
    total = total_steps(sampler is not None)
    done = 0
    connectivity_result: dict = {}
    connectivity_thread = threading.Thread(
        target=lambda: connectivity_result.update(measure_connectivity(host)), daemon=True
    )
    connectivity_thread.start()

    def step(label: str, action: Callable[[], object], record: bool = False):
        nonlocal done
        if stop.is_set():
            raise InfoCancelled()
        progress(done, total, label)
        started = time.monotonic()
        try:
            return action()
        except InfoCancelled:
            raise
        except Exception:
            return None
        finally:
            done += 1
            if record:
                raw.latencies.append(time.monotonic() - started)
            time.sleep(QUERY_PAUSE)

    for group, key, path in TEXT_STEPS:
        if key == "time":
            before = now_fn()
            raw.text[key] = step(group, lambda path=path: fetcher.get(path), record=True)
            raw.clock = (before, now_fn())
        else:
            raw.text[key] = step(group, lambda path=path: fetcher.get(path), record=True)

    now = now_fn()
    for channel in CHANNELS:
        raw.oldest[channel] = step(
            "Buscando la grabación más antigua", lambda channel=channel: fetcher.find(channel, EPOCH, now)
        )
    midnight = datetime.combine(now.date(), datetime.min.time())
    for channel in CHANNELS:
        raw.today[channel] = step(
            "Revisando las grabaciones de hoy",
            lambda channel=channel: fetcher.find(channel, midnight, midnight + timedelta(hours=23, minutes=59, seconds=59)),
        )

    if sampler is not None:
        raw.samples = {}
        start = (now_fn() - SAMPLE_AGE).replace(microsecond=0)
        for channel in CHANNELS:
            raw.samples[channel] = step(
                "Analizando el video de cada canal",
                lambda channel=channel: sampler.sample(channel, start, start + timedelta(seconds=SAMPLE_SECONDS)),
            )

    progress(done, total, "Midiendo la conectividad")

    def measure_gateway():
        gateway = connectivity_result.get("gateway")
        return measure_gateway_ping(gateway) if gateway else None

    connectivity_thread.join(timeout=20)
    raw.connectivity = dict(connectivity_result) or None
    raw.gateway_ping = step("Midiendo la conectividad", measure_gateway)
    return raw


# -- armado del informe -------------------------------------------------------


def _kv(raw: Raw, key: str) -> dict[str, str] | None:
    text = raw.text.get(key)
    return parse_kv(text) if text is not None else None


def _first(mapping: dict[str, str] | None, key: str) -> str:
    return mapping.get(key, NOT_AVAILABLE) if mapping else NOT_AVAILABLE


def _clip_times(items: list[dict[str, str]]) -> list[tuple[datetime, datetime, int]]:
    clips = []
    for item in items:
        start, end = item.get("StartTime"), item.get("EndTime")
        if start and end:
            clips.append(
                (
                    datetime.strptime(start, "%Y-%m-%d %H:%M:%S"),
                    datetime.strptime(end, "%Y-%m-%d %H:%M:%S"),
                    int(item.get("Length", "0") or 0),
                )
            )
    return sorted(clips)


def recording_rate(oldest: dict[int, list[dict[str, str]] | None]) -> float | None:
    """Bytes por segundo, sumando los canales, medidos sobre la primera
    página de clips de cada canal (100 clips seguidos)."""
    total = 0.0
    for items in oldest.values():
        clips = _clip_times(items or [])
        if not clips:
            continue
        seconds = (clips[-1][1] - clips[0][0]).total_seconds()
        if seconds > 0:
            total += sum(length for *_, length in clips) / seconds
    return total or None


def today_coverage(clips: list[tuple[datetime, datetime, int]], now: datetime) -> tuple[float, int]:
    """(fracción de lo transcurrido hoy que tiene grabación, huecos)."""
    midnight = datetime.combine(now.date(), datetime.min.time())
    elapsed = (now - midnight).total_seconds()
    covered, gaps, previous_end = 0.0, 0, None
    for start, end, _ in clips:
        start, end = max(start, midnight), min(end, now)
        if end > start:
            covered += (end - start).total_seconds()
        if previous_end is not None and (start - previous_end).total_seconds() > COVERAGE_GAP_SECONDS:
            gaps += 1
        previous_end = max(previous_end, end) if previous_end else end
    return (covered / elapsed if elapsed > 0 else 0.0, gaps)


def build_sections(raw: Raw, host: str, now: datetime) -> list[Section]:
    sections: list[Section] = []
    checks = Section("Resumen")
    sections.append(checks)

    sysinfo, name, dtype = _kv(raw, "sysinfo"), _kv(raw, "name"), _kv(raw, "type")
    cls, software, hardware, vendor = _kv(raw, "class"), _kv(raw, "software"), _kv(raw, "hardware"), _kv(raw, "vendor")
    network, ntp, locales = _kv(raw, "network"), _kv(raw, "ntp"), _kv(raw, "locales")
    titles, encode, recordmode, storage = _kv(raw, "titles"), _kv(raw, "encode"), _kv(raw, "recordmode"), _kv(raw, "storage")

    # -- equipo
    equipment = Section("Equipo")
    equipment.add("Fabricante", _first(vendor, "vendor"), TAG_DVR)
    equipment.add("Modelo", _first(dtype, "type"), TAG_DVR)
    equipment.add("Clase", _first(cls, "class"), TAG_DVR)
    equipment.add("Nombre", _first(name, "name"), TAG_DVR)
    equipment.add("Número de serie", _first(sysinfo, "serialNumber"), TAG_DVR)
    equipment.add("Procesador", _first(sysinfo, "processor"), TAG_DVR)
    equipment.add("Serie de actualización", _first(sysinfo, "updateSerial"), TAG_DVR)
    firmware = _first(software, "version")
    equipment.add("Firmware", firmware, TAG_DVR)
    firmware_old = False
    build = re.search(r"(\d{2})/(\d{2})/(\d{4})", firmware)
    if build:
        age = now.year - int(build.group(3))
        firmware_old = age >= FIRMWARE_OLD_YEARS
        equipment.add("Antigüedad del firmware", f"compilación de {build.group(3)} (≈ {age} años)", TAG_CALC)
    equipment.add("Hardware", _first(hardware, "version"), TAG_DVR)
    sections.append(equipment)

    # -- red
    net = Section("Red")
    iface = _first(network, "Network.DefaultInterface")
    prefix = f"Network.{iface}." if network and iface != NOT_AVAILABLE else "Network.eth0."
    dvr_ip = _first(network, prefix + "IPAddress")
    mask = _first(network, prefix + "SubnetMask")
    net.add("Dirección IP", dvr_ip, TAG_DVR)
    net.add("Máscara", mask, TAG_DVR)
    net.add("Puerta de enlace", _first(network, prefix + "DefaultGateway"), TAG_DVR)
    dhcp = _first(network, prefix + "DhcpEnable")
    net.add("DHCP", {"false": "desactivado (IP fija)", "true": "activado"}.get(dhcp, dhcp), TAG_DVR)
    dns = [v for k, v in sorted((network or {}).items()) if k.startswith(prefix + "DnsServers")]
    net.add("DNS", ", ".join(dns) if dns else NOT_AVAILABLE, TAG_DVR)
    net.add("Dirección MAC", _first(network, prefix + "PhysicalAddress"), TAG_DVR)
    net.add("MTU", _first(network, prefix + "MTU"), TAG_DVR)
    net.add("Nombre en la red", _first(network, "Network.Hostname"), TAG_DVR)
    if ntp:
        ntp_state = "activada" if ntp.get("NTP.Enable") == "true" else "desactivada"
        net.add("Sincronización NTP", f"{ntp_state}, servidor {ntp.get('NTP.Address', NOT_AVAILABLE)}", TAG_DVR)
        try:
            private = ipaddress.ip_address(ntp.get("NTP.Address", "")).is_private
            net.add("Origen de la hora", "servidor en la red local (no depende de Internet)" if private else "servidor externo", TAG_CALC)
        except ValueError:
            pass
    conn = raw.connectivity or {}
    for port, label in DVR_PORTS:
        if port in conn.get("ports", {}):
            is_open, ms = conn["ports"][port]
            net.add(f"Puerto {port} ({label})", f"abierto, conecta en {ms:.1f} ms" if is_open else "cerrado o sin respuesta", TAG_MEASURED)
    if conn.get("local_ip") and dvr_ip != NOT_AVAILABLE and mask != NOT_AVAILABLE:
        try:
            same = ipaddress.ip_address(conn["local_ip"]) in ipaddress.ip_network(f"{dvr_ip}/{mask}", strict=False)
            net.add("Misma subred que este equipo", "sí" if same else "no", TAG_CALC)
        except ValueError:
            pass
    sections.append(net)

    # -- hora
    clock = Section("Hora")
    dvr_time = parse_time(raw.text.get("time") or "")
    clock.add("Hora del DVR", dvr_time.strftime("%d/%m/%Y %H:%M:%S") if dvr_time else NOT_AVAILABLE, TAG_DVR)
    clock.add("Zona horaria (código Dahua)", _first(ntp, "NTP.TimeZone"), TAG_DVR)
    if locales:
        clock.add("Horario de verano", "activado" if locales.get("Locales.DSTEnable") == "true" else "desactivado", TAG_DVR)
    offset = None
    if dvr_time and raw.clock:
        pc_mid = raw.clock[0] + (raw.clock[1] - raw.clock[0]) / 2
        offset = (dvr_time - pc_mid).total_seconds()
        clock.add("Desfase con este equipo", f"{offset:+.1f} s", TAG_MEASURED)
    sections.append(clock)

    # -- almacenamiento
    disk = Section("Almacenamiento")
    disk_ok = None
    total_kb = 0
    if storage:
        state = _first(storage, "info[0].State")
        disk.add("Disco", f"{_first(storage, 'info[0].Name')} — estado {state}", TAG_DVR)
        errors = 0
        index = 0
        while f"info[0].Detail[{index}].Path" in storage:
            base = f"info[0].Detail[{index}]."
            total, used = int(storage[base + "TotalBytes"]), int(storage[base + "UsedBytes"])
            total_kb += total
            errors += storage.get(base + "IsError") == "true"
            # El DVR llama "Bytes" a estas cifras, pero suman ≈ 1.7 TiB si son
            # KB (y con bytes no cabría ni una hora de video): se tratan como KB.
            pct = f"{100 * used / total:.0f} %" if total else "—"
            disk.add(f"Partición {storage[base + 'Path']}", f"{fmt_bytes(total * 1024)}, usado {pct}", TAG_DVR)
            index += 1
        disk.add("Capacidad total", fmt_bytes(total_kb * 1024), TAG_CALC)
        if total_kb and all(storage.get(f"info[0].Detail[{i}].UsedBytes") == storage.get(f"info[0].Detail[{i}].TotalBytes") for i in range(index)):
            disk.add("Ocupación", "100 %: el DVR sobrescribe lo más antiguo (grabación circular)", TAG_INFERRED)
        disk.add("Diagnóstico SMART", "no ofrecido por este modelo" if storage.get("info[0].HealthDataFlag") == "0" else _first(storage, "info[0].HealthDataFlag"), TAG_DVR)
        disk_ok = state == "Success" and errors == 0
    else:
        disk.add("Disco", NOT_AVAILABLE)
    oldest_starts = [c[0] for items in raw.oldest.values() for c in _clip_times(items or [])[:1]]
    retention_days = None
    if oldest_starts:
        oldest = min(oldest_starts)
        retention_days = (now - oldest).total_seconds() / 86400
        disk.add("Grabación más antigua", oldest.strftime("%d/%m/%Y %H:%M"), TAG_MEASURED)
        disk.add("Retención real", fmt_duration_days(retention_days), TAG_MEASURED)
    rate = recording_rate(raw.oldest)
    if rate:
        per_day = rate * 86400
        disk.add("Consumo estimado", f"{fmt_bytes(per_day)} por día ({len(CHANNELS)} canales)", TAG_CALC)
        if total_kb:
            capacity_days = total_kb * 1024 / per_day
            disk.add("Capacidad según ese consumo", fmt_duration_days(capacity_days), TAG_CALC)
            if retention_days is not None and retention_days < 0.6 * capacity_days:
                disk.add(
                    "Nota",
                    "la retención real es menor que la capacidad (posible límite de grabación configurado o espacio compartido)",
                    TAG_INFERRED,
                )
    sections.append(disk)

    # -- canales
    recording_channels = 0
    channel_sections: list[Section] = []
    for index, channel in enumerate(CHANNELS):
        sec = Section(f"Canal {channel}")
        sec.add("Nombre", _first(titles, f"ChannelTitle[{index}].Name"), TAG_DVR)
        for stream, label in (("MainFormat", "Flujo principal (configurado)"), ("ExtraFormat", "Subflujo (configurado)")):
            base = f"Encode[{index}].{stream}[0]."
            if encode and base + "Video.resolution" in encode:
                text = (
                    f"{encode[base + 'Video.resolution']} a {encode.get(base + 'Video.FPS', '?')} fps, "
                    f"{encode.get(base + 'Video.Compression', '?')}, {encode.get(base + 'Video.BitRate', '?')} kbps "
                    f"{encode.get(base + 'Video.BitRateControl', '')}".strip()
                )
                sec.add(label, text, TAG_DVR)
            else:
                sec.add(label, NOT_AVAILABLE)
        mode = _first(recordmode, f"RecordMode[{index}].Mode")
        sec.add("Modo de grabación", "automático" if mode == "0" else mode, TAG_DVR)
        sample = (raw.samples or {}).get(channel)
        if raw.samples is None:
            sec.add("Video real grabado", "omitido: en vivo no se mezclan descargas con el video", TAG_INFERRED)
        elif sample:
            sec.add(
                "Video real grabado",
                f"{sample.width}x{sample.height} a {sample.fps:.0f} fps, {sample.codec}, ≈ {sample.kbps:.0f} kbps",
                TAG_MEASURED,
            )
        else:
            sec.add("Video real grabado", NOT_AVAILABLE)
        clips = _clip_times(raw.today.get(channel) or [])
        if raw.today.get(channel) is None:
            sec.add("Grabando ahora", NOT_AVAILABLE)
        elif clips:
            last_end = max(end for _, end, _ in clips)
            recording = (now - last_end).total_seconds() <= RECORDING_NOW_SECONDS
            recording_channels += recording
            sec.add("Grabando ahora", "sí" if recording else "no", TAG_INFERRED)
            sec.add("Última grabación", last_end.strftime("%H:%M:%S"), TAG_MEASURED)
            coverage, gaps = today_coverage(clips, now)
            sec.add("Cobertura de hoy", f"{100 * coverage:.2f} % ({gaps} {'hueco' if gaps == 1 else 'huecos'} de más de {COVERAGE_GAP_SECONDS} s)", TAG_CALC)
        else:
            sec.add("Grabando ahora", "no (sin grabaciones hoy)", TAG_INFERRED)
        channel_sections.append(sec)
    sections.extend(channel_sections)

    # -- conectividad
    link = Section("Conectividad desde este equipo")
    ping = conn.get("ping") or {}
    if ping.get("avg") is not None:
        link.add("Ping al DVR", f"mín {ping['min']:.1f} / prom {ping['avg']:.1f} / máx {ping['max']:.1f} ms, variación {ping['mdev']:.1f} ms, pérdida {ping['loss']:.0f} %", TAG_MEASURED)
        if ping.get("ttl"):
            link.add("Saltos estimados", str(hops_from_ttl(ping["ttl"])), TAG_CALC)
    else:
        link.add("Ping al DVR", NOT_AVAILABLE)
    gw = raw.gateway_ping or {}
    if gw.get("avg") is not None:
        link.add(f"Ping a la puerta de enlace ({conn.get('gateway')})", f"prom {gw['avg']:.1f} ms", TAG_MEASURED)
    if raw.latencies:
        link.add("Respuesta de las consultas", f"{1000 * sum(raw.latencies) / len(raw.latencies):.0f} ms en promedio por consulta", TAG_MEASURED)
    if conn.get("interface"):
        speed = f", enlace a {conn['link_mbps']} Mbps" if conn.get("link_mbps") else ""
        link.add("Interfaz de este equipo", f"{conn['interface']} ({conn.get('local_ip', '?')}){speed}", TAG_MEASURED)
    link.add("Límites de esta app", "2 descargas y 2 consultas ligeras a la vez (el DVR tolera 3 sesiones de clips)", TAG_CALC)
    sections.append(link)

    # -- resumen (semáforo)
    checks.add("✔" if raw.text.get("sysinfo") is not None else "✖", "DVR alcanzable")
    if offset is not None:
        checks.add("✔" if abs(offset) <= CLOCK_TOLERANCE else "⚠", f"Hora {'sincronizada' if abs(offset) <= CLOCK_TOLERANCE else 'desfasada'} ({offset:+.1f} s)")
    if disk_ok is not None:
        checks.add("✔" if disk_ok else "⚠", "Disco sin errores" if disk_ok else "Disco con errores o estado anormal")
    if any(v is not None for v in raw.today.values()):
        checks.add("✔" if recording_channels == len(CHANNELS) else "⚠", f"Grabando {recording_channels} de {len(CHANNELS)} canales")
    if ping.get("avg") is not None:
        checks.add("✔" if ping["avg"] < 50 and (ping["loss"] or 0) == 0 else "⚠", f"Latencia {'baja' if ping['avg'] < 50 else 'alta'} ({ping['avg']:.0f} ms)")
    if firmware_old:
        checks.add("⚠", "Firmware antiguo")

    unavailable = Section("Lo que este modelo no ofrece")
    unavailable.add("", "estado de cada cámara (getCameraState responde 400), diagnóstico SMART del disco, lista de clientes conectados, configuración HTTP (403 para este usuario) y nombres de dispositivos de almacenamiento", "")
    sections.append(unavailable)
    return sections


def format_report(sections: list[Section], host: str, generated: datetime) -> str:
    lines = [f"Información del DVR {host} — {generated.strftime('%d/%m/%Y %H:%M:%S')}", ""]
    for section in sections:
        lines.append(f"== {section.title} ==")
        for row in section.rows:
            tag = f"  [{row.tag}]" if row.tag else ""
            if section.title == "Resumen":
                lines.append(f"{row.label} {row.value}")
            elif row.label:
                lines.append(f"{row.label}: {row.value}{tag}")
            else:
                lines.append(row.value)
        lines.append("")
    lines.append("[DVR] lo dice el equipo · [Medido] medido desde este equipo · [Calculado] deducido · [Inferido] suposición razonable")
    return "\n".join(lines)
