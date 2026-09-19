from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timedelta

import cv2
from PySide6.QtCore import QTimer
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


def _collect_job(host: str, username: str, password: str, is_live: bool, events: queue.Queue, stop: threading.Event) -> None:
    """Corre en un hilo aparte. Solo deja avisos en `events`: NUNCA referencia
    la ventana ni emite señales de Qt -- si el hilo fuera el último dueño de
    la ventana, la destruiría desde un hilo que no es el de la interfaz y el
    proceso entero moriría ("Bus error") al cerrarla mientras carga."""
    try:
        fetcher = _FunnelFetcher(host, username, password, stop)
        sampler = None if is_live else _FunnelSampler(host, username, password, stop)
        raw = collect(host, fetcher, sampler, lambda done, total, label: events.put(("progress", done, total, label)), stop)
        now = datetime.now()
        events.put(("report", format_report(build_sections(raw, host, now), host, now)))
    except InfoCancelled:
        events.put(("failed", ""))
    except Exception as exc:
        events.put(("failed", str(exc)))


def _speed_job(host: str, username: str, password: str, events: queue.Queue, stop: threading.Event) -> None:
    start = (datetime.now() - SAMPLE_AGE).replace(microsecond=0)
    started = time.monotonic()
    try:
        path = download_client.submit(
            host, username, password, 1, start, start + timedelta(seconds=SPEED_TEST_SECONDS),
            DownloadPriority.INTERACTIVE, stop,
        ).result(timeout=DOWNLOAD_WAIT)
    except Exception:
        path = None
    elapsed = time.monotonic() - started
    if path is None:
        events.put(("speed", "Velocidad de descarga: no disponible"))
        return
    size = path.stat().st_size
    path.unlink(missing_ok=True)
    events.put(
        (
            "speed",
            f"Velocidad de descarga: {fmt_bytes(size / elapsed)}/s ({size * 8 / elapsed / 1e6:.0f} Mbps), "
            f"{fmt_bytes(size)} en {elapsed:.1f} s  [Medido]",
        )
    )


class DvrInfoDialog(QDialog):
    """Ventana "Información del DVR": al abrirse consulta todo (una consulta
    a la vez, con barra de progreso y botón Cancelar) y muestra el informe
    completo cuando está listo. No se actualiza sola: solo con "Actualizar"."""

    EVENT_POLL_MS = 100

    def __init__(self, host: str, username: str, password: str, is_live: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Información del DVR")
        self.resize(760, 680)
        self._host, self._username, self._password = host, username, password
        self._is_live = is_live
        self._stop = threading.Event()
        self._report = ""
        self._running = False
        self._events: queue.Queue = queue.Queue()  # avisos de los hilos; se leen aquí, en el hilo de la interfaz

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
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.EVENT_POLL_MS)
        self._poll_timer.timeout.connect(self._drain_events)
        self._poll_timer.start()

        self.start()

    # -- recolección ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop = threading.Event()
        self._events = queue.Queue()  # los avisos tardíos de una corrida cancelada se descartan con la cola vieja
        steps = total_steps(not self._is_live)
        self._bar.setRange(0, steps)
        self._bar.setValue(0)
        self._step_label.setText("Consultando al DVR…")
        self._text.clear()
        self._set_busy(True)
        args = (self._host, self._username, self._password, self._is_live, self._events, self._stop)
        threading.Thread(target=_collect_job, args=args, daemon=True).start()

    def _drain_events(self) -> None:
        while True:
            try:
                kind, *payload = self._events.get_nowait()
            except queue.Empty:
                return
            {"progress": self._on_progress, "report": self._on_report, "failed": self._on_failed, "speed": self._on_speed}[kind](*payload)

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
        args = (self._host, self._username, self._password, self._events, self._stop)
        threading.Thread(target=_speed_job, args=args, daemon=True).start()

    def _on_speed(self, line: str) -> None:
        self._speed_button.setEnabled(not self._running and not self._is_live)
        self._step_label.setText("Listo.")
        self._report = f"{self._report}\n{line}"
        self._text.setPlainText(self._report)

    def closeEvent(self, event) -> None:
        self._stop.set()
        self._poll_timer.stop()
        super().closeEvent(event)
