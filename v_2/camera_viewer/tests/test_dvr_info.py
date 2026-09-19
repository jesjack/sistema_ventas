"""Pruebas de dvr_info.py con respuestas REALES del DVR guardadas en fixtures/dvr_info/.
Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_dvr_info -v"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from camera_viewer import dvr_info
from camera_viewer.dvr_info import InfoCancelled, StreamSample
from camera_viewer.light_query_manager import parse_items

FIXTURES = Path(__file__).parent / "fixtures" / "dvr_info"
NOW = datetime(2026, 9, 19, 12, 11, 40)  # el DVR real dijo 12:11:39 al guardar las respuestas

PATH_TO_FIXTURE = {path: key for _, key, path in dvr_info.TEXT_STEPS}
KEY_TO_FILE = {
    "sysinfo": "getSystemInfo", "name": "getMachineName", "type": "getDeviceType", "class": "getDeviceClass",
    "software": "getSoftwareVersion", "hardware": "getHardwareVersion", "vendor": "getVendor", "time": "getCurrentTime",
    "locales": "Locales", "network": "Network", "ntp": "NTP", "titles": "ChannelTitle", "encode": "Encode",
    "recordmode": "RecordMode", "storage": "storage",
}


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


class FakeFetcher:
    def __init__(self, fail_keys: set[str] | None = None) -> None:
        self.fail_keys = fail_keys or set()
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    def _enter(self, label: str) -> None:
        self.calls.append(label)
        self.active += 1
        self.max_active = max(self.max_active, self.active)

    def get(self, path: str) -> str:
        self._enter(path)
        try:
            key = PATH_TO_FIXTURE[path]
            if key in self.fail_keys:
                raise RuntimeError("caído")
            return fixture(KEY_TO_FILE[key])
        finally:
            self.active -= 1

    def find(self, channel: int, start: datetime, end: datetime) -> list[dict[str, str]]:
        self._enter(f"find:{channel}:{start:%Y-%m-%d}")
        try:
            if start.year == 2000:
                return parse_items(fixture("oldest"))
            # hoy: una grabación continua desde medianoche hasta "ahora" (el clip en curso termina en "ahora")
            return [{"StartTime": "2026-09-19 00:00:00", "EndTime": "2026-09-19 12:11:40", "Length": "1000"}]
        finally:
            self.active -= 1


FAKE_CONNECTIVITY = {
    "interface": "enp3s0", "local_ip": "192.168.1.10", "link_mbps": 1000, "gateway": "192.168.1.10",
    "ping": {"loss": 0.0, "min": 8.1, "avg": 9.2, "max": 12.0, "mdev": 1.1, "ttl": 64},
    "ports": {80: (True, 1.2), 554: (True, 1.3), 37777: (False, None)},
}


def run_collect(fetcher, sampler=None, stop=None, progress=None):
    with mock.patch.object(dvr_info, "QUERY_PAUSE", 0), \
            mock.patch.object(dvr_info, "measure_connectivity", return_value=FAKE_CONNECTIVITY), \
            mock.patch.object(dvr_info, "measure_gateway_ping", return_value={"avg": 0.4}):
        return dvr_info.collect("192.168.1.108", fetcher, sampler, progress or (lambda *a: None), stop or threading.Event(), lambda: NOW)


def report(raw) -> str:
    return dvr_info.format_report(dvr_info.build_sections(raw, "192.168.1.108", NOW), "192.168.1.108", NOW)


class ParserTests(unittest.TestCase):
    def test_parse_kv_strips_table_and_list_prefixes(self) -> None:
        network = dvr_info.parse_kv(fixture("Network"))
        self.assertEqual(network["Network.eth0.IPAddress"], "192.168.1.108")
        self.assertEqual(dvr_info.parse_kv(fixture("storage"))["info[0].State"], "Success")
        self.assertEqual(dvr_info.parse_kv(fixture("getSystemInfo"))["serialNumber"], "6L00943PAZ627B4")

    def test_parse_ping(self) -> None:
        output = "64 bytes from 192.168.1.108: icmp_seq=1 ttl=64 time=8.9 ms\n8 packets transmitted, 8 received, 0% packet loss, time 1409ms\nrtt min/avg/max/mdev = 8.231/8.732/9.312/0.313 ms"
        result = dvr_info.parse_ping(output)
        self.assertEqual((result["loss"], result["min"], result["avg"], result["ttl"]), (0.0, 8.231, 8.732, 64))

    def test_hops_from_ttl(self) -> None:
        self.assertEqual([dvr_info.hops_from_ttl(t) for t in (64, 63, 128, 120, 255)], [0, 1, 0, 8, 0])

    def test_parse_route(self) -> None:
        self.assertEqual(dvr_info.parse_route("192.168.1.108 dev enp3s0 src 192.168.1.10 uid 1000"), ("enp3s0", "192.168.1.10"))

    def test_today_coverage_counts_gaps(self) -> None:
        clips = [
            (datetime(2026, 9, 19, 0, 0, 0), datetime(2026, 9, 19, 6, 0, 0), 1),
            (datetime(2026, 9, 19, 6, 0, 0), datetime(2026, 9, 19, 7, 0, 0), 1),  # contiguo: no es hueco
            (datetime(2026, 9, 19, 8, 0, 0), datetime(2026, 9, 19, 12, 0, 0), 1),  # hueco de 1 h
        ]
        coverage, gaps = dvr_info.today_coverage(clips, datetime(2026, 9, 19, 12, 0, 0))
        self.assertEqual(gaps, 1)
        self.assertAlmostEqual(coverage, 11 / 12, places=3)


class CollectAndReportTests(unittest.TestCase):
    def test_full_report_from_real_responses(self) -> None:
        text = report(run_collect(FakeFetcher(), sampler=mock.Mock(sample=mock.Mock(return_value=StreamSample(960, 1080, 30.0, "H264", 2100.0)))))
        for expected in (
            "Modelo: DH-XVR1A04", "Fabricante: Dahua", "Número de serie: 6L00943PAZ627B4", "Procesador: ST7108",
            "Firmware: 3.218.0000002.5,build:01/03/2019", "compilación de 2019 (≈ 7 años)",
            "Dirección IP: 192.168.1.108", "Dirección MAC: 24:52:6a:07:bb:86", "DHCP: desactivado (IP fija)",
            "DNS: 8.8.8.8, 8.8.4.4", "servidor en la red local", "Misma subred que este equipo: sí",
            "Puerto 37777 (datos Dahua): cerrado", "Desfase con este equipo: -1.0 s",
            "Horario de verano: desactivado", "Partición /dev/sda0", "Capacidad total: 1.7 TB",
            "Ocupación: 100 %", "Grabación más antigua: 14/09/2026 06:00", "Retención real: 5.3 días",
            "Nombre: CAM 1", "960x1080 a 30 fps, H.264, 2048 kbps CBR", "352x240 a 15 fps, H.264, 320 kbps CBR",
            "960x1080 a 30 fps, H264, ≈ 2100 kbps", "Grabando ahora: sí", "Cobertura de hoy: 100.00 % (0 huecos de más de 2 s)",
            "Ping al DVR: mín 8.1", "✔ DVR alcanzable", "✔ Hora sincronizada", "✔ Disco sin errores",
            "✔ Grabando 4 de 4 canales", "⚠ Firmware antiguo", "Lo que este modelo no ofrece",
        ):
            self.assertIn(expected, text)

    def test_a_failed_step_shows_not_available_and_the_rest_continues(self) -> None:
        text = report(run_collect(FakeFetcher(fail_keys={"network", "storage"})))
        self.assertIn("Dirección IP: no disponible", text)
        self.assertIn("Disco: no disponible", text)
        self.assertIn("Modelo: DH-XVR1A04", text)  # lo demás sigue apareciendo

    def test_live_mode_skips_video_samples(self) -> None:
        raw = run_collect(FakeFetcher(), sampler=None)
        self.assertIsNone(raw.samples)
        self.assertIn("omitido: en vivo no se mezclan descargas con el video", report(raw))

    def test_queries_are_strictly_one_at_a_time_and_progress_reaches_total(self) -> None:
        fetcher, seen = FakeFetcher(), []
        run_collect(fetcher, progress=lambda done, total, label: seen.append((done, total)))
        self.assertEqual(fetcher.max_active, 1)
        self.assertEqual(seen[-1][0], seen[-1][1] - 1)  # último aviso, justo antes del paso final
        self.assertEqual(len(fetcher.calls), len(dvr_info.TEXT_STEPS) + 2 * len(dvr_info.CHANNELS))
        self.assertEqual(seen[0][1], dvr_info.total_steps(False))

    def test_cancel_stops_before_the_next_query(self) -> None:
        stop, fetcher = threading.Event(), FakeFetcher()
        stop.set()
        with self.assertRaises(InfoCancelled):
            run_collect(fetcher, stop=stop)
        self.assertEqual(fetcher.calls, [])

    def test_never_requests_credentials_configs(self) -> None:
        forbidden = ("User", "Password", "DDNS", "Email", "Mail")
        for _, _, path in dvr_info.TEXT_STEPS:
            self.assertFalse(any(word in path for word in forbidden), path)

    def test_recording_rate_uses_bytes_per_second_across_channels(self) -> None:
        items = parse_items(fixture("oldest"))
        rate = dvr_info.recording_rate({1: items, 2: None})
        self.assertGreater(rate * 86400, 20e9)  # ≈ 22 GB/día por canal a ~2 Mbps
        self.assertLess(rate * 86400, 30e9)


if __name__ == "__main__":
    unittest.main()
