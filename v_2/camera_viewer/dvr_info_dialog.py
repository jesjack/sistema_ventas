from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import cv2
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import download_client
from .download_manager import DownloadPriority
from .dvr_info import (
    SAMPLE_AGE,
    InfoCancelled,
    StreamSample,
    build_sections,
    collect,
    fmt_bytes,
    format_report,
    total_steps,
)
from .light_query_manager import LightPriority

QUERY_WAIT = 150  # segundos máximos esperando una consulta (el servicio ya reintenta)
DOWNLOAD_WAIT = 90
SPEED_TEST_SECONDS = 15


class _FunnelFetcher:
    """Consultas al DVR por el carril ligero del embudo (prioridad de usuario)."""

    def __init__(self, host: str, username: str, password: str, stop: threading.Event) -> None:
        self._args = (host, username, password)
        self._stop = stop

    def get(self, path: str) -> str:
        return download_client.get(*self._args, path, LightPriority.USER, self._stop).result(timeout=QUERY_WAIT)

    def find(self, channel: int, start: datetime, end: datetime) -> list[dict[str, str]]:
        future = download_client.find_files(*self._args, channel, start, end, 1, LightPriority.USER, self._stop)
        return future.result(timeout=QUERY_WAIT)


class _FunnelSampler:
    """Baja unos segundos de un clip ya cerrado por el carril de descargas
    (prioridad más baja: nunca le gana el turno a la reproducción) y mide el
    video real: resolución, cuadros por segundo, códec y bitrate."""

    def __init__(self, host: str, username: str, password: str, stop: threading.Event) -> None:
        self._args = (host, username, password)
        self._stop = stop

    def sample(self, channel: int, start: datetime, end: datetime) -> StreamSample | None:
        path = download_client.submit(
            *self._args, channel, start, end, DownloadPriority.BACKGROUND, self._stop
        ).result(timeout=DOWNLOAD_WAIT)
        if path is None:
            return None
        try:
            size = path.stat().st_size
            capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
            try:
                ok, frame = capture.read()
                if not ok:
                    return None
                height, width = frame.shape[:2]
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                fourcc = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
                codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).strip() or "desconocido"
            finally:
                capture.release()
            seconds = (end - start).total_seconds()
            return StreamSample(width, height, fps, codec, size * 8 / seconds / 1000)
        finally:
            path.unlink(missing_ok=True)


class DvrInfoDialog(QDialog):
    """Ventana "Información del DVR": al abrirse consulta todo (una consulta
    a la vez, con barra de progreso y botón Cancelar) y muestra el informe
    completo cuando está listo. No se actualiza sola: solo con "Actualizar"."""

    _progress = Signal(int, int, str)
    _report_ready = Signal(str)
    _collect_failed = Signal(str)
    _speed_ready = Signal(str)

    def __init__(self, host: str, username: str, password: str, is_live: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Información del DVR")
        self.resize(760, 680)
        self._host, self._username, self._password = host, username, password
        self._is_live = is_live
        self._stop = threading.Event()
        self._report = ""
        self._running = False

        self._step_label = QLabel()
        self._bar = QProgressBar()
        self._bar.setFormat("%p %")
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("monospace", 10))
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._cancel_button = QPushButton("Cancelar")
        self._refresh_button = QPushButton("Actualizar")
        self._copy_button = QPushButton("Copiar")
        self._speed_button = QPushButton("Probar velocidad de descarga")
        self._close_button = QPushButton("Cerrar")
        if is_live:
            self._speed_button.setEnabled(False)
            self._speed_button.setToolTip("Disponible en la vista de grabaciones (no se mezclan descargas con el video en vivo)")

        buttons = QHBoxLayout()
        for button in (self._cancel_button, self._refresh_button, self._copy_button, self._speed_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self._close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._step_label)
        layout.addWidget(self._bar)
        layout.addWidget(self._text, stretch=1)
        layout.addLayout(buttons)

        self._cancel_button.clicked.connect(self._cancel)
        self._refresh_button.clicked.connect(self.start)
        self._copy_button.clicked.connect(self._copy)
        self._speed_button.clicked.connect(self._start_speed_test)
        self._close_button.clicked.connect(self.close)
        self._progress.connect(self._on_progress)
        self._report_ready.connect(self._on_report)
        self._collect_failed.connect(self._on_failed)
        self._speed_ready.connect(self._on_speed)

        self.start()

    # -- recolección ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop = threading.Event()
        steps = total_steps(not self._is_live)
        self._bar.setRange(0, steps)
        self._bar.setValue(0)
        self._step_label.setText("Consultando al DVR…")
        self._text.clear()
        self._set_busy(True)
        threading.Thread(target=self._collect_worker, args=(self._stop,), daemon=True).start()

    def _collect_worker(self, stop: threading.Event) -> None:
        try:
            fetcher = _FunnelFetcher(self._host, self._username, self._password, stop)
            sampler = None if self._is_live else _FunnelSampler(self._host, self._username, self._password, stop)
            raw = collect(self._host, fetcher, sampler, lambda done, total, label: self._progress.emit(done, total, label), stop)
            now = datetime.now()
            self._report_ready.emit(format_report(build_sections(raw, self._host, now), self._host, now))
        except InfoCancelled:
            self._collect_failed.emit("")
        except Exception as exc:
            self._collect_failed.emit(str(exc))

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self._bar.setMaximum(total)
        self._bar.setValue(done)
        self._step_label.setText(f"{label}… {min(done + 1, total)}/{total}")

    def _on_report(self, text: str) -> None:
        self._running = False
        self._report = text
        self._text.setPlainText(text)
        self._step_label.setText("Listo.")
        self._bar.setValue(self._bar.maximum())
        self._set_busy(False)

    def _on_failed(self, message: str) -> None:
        self._running = False
        self._step_label.setText(f"No se pudo completar la consulta: {message}" if message else "Consulta cancelada.")
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._cancel_button.setVisible(busy)
        self._bar.setVisible(busy)
        self._refresh_button.setEnabled(not busy)
        self._copy_button.setEnabled(not busy and bool(self._report))
        self._speed_button.setEnabled(not busy and not self._is_live)

    def _cancel(self) -> None:
        self._stop.set()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._text.toPlainText())
        self._step_label.setText("Copiado al portapapeles.")

    # -- prueba de velocidad (botón aparte) ------------------------------------

    def _start_speed_test(self) -> None:
        self._speed_button.setEnabled(False)
        self._step_label.setText(f"Descargando {SPEED_TEST_SECONDS} s de video para medir la velocidad… (puede afectar un instante la reproducción)")
        threading.Thread(target=self._speed_worker, args=(self._stop,), daemon=True).start()

    def _speed_worker(self, stop: threading.Event) -> None:
        start = (datetime.now() - SAMPLE_AGE).replace(microsecond=0)
        started = time.monotonic()
        try:
            path = download_client.submit(
                self._host, self._username, self._password, 1, start, start + timedelta(seconds=SPEED_TEST_SECONDS),
                DownloadPriority.INTERACTIVE, stop,
            ).result(timeout=DOWNLOAD_WAIT)
        except Exception:
            path = None
        elapsed = time.monotonic() - started
        if path is None:
            self._speed_ready.emit("Velocidad de descarga: no disponible")
            return
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        self._speed_ready.emit(
            f"Velocidad de descarga: {fmt_bytes(size / elapsed)}/s ({size * 8 / elapsed / 1e6:.0f} Mbps), "
            f"{fmt_bytes(size)} en {elapsed:.1f} s  [Medido]"
        )

    def _on_speed(self, line: str) -> None:
        self._speed_button.setEnabled(not self._running and not self._is_live)
        self._step_label.setText("Listo.")
        self._report = f"{self._report}\n{line}"
        self._text.setPlainText(self._report)

    def closeEvent(self, event) -> None:
        self._stop.set()
        super().closeEvent(event)
