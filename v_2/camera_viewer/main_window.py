from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta

from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QVBoxLayout, QWidget

from .calendar_panel import CalendarPanel
from .camera_grid import CameraGrid
from .connection_panel import ConnectionPanel
from .dvr_client import Clip, DEFAULT_CHANNELS, DVRClient
from .timeline_widget import TimelineWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Visor de camaras")
        self.resize(1400, 900)

        self.client = DVRClient(self)
        self._clips_by_channel: dict[int, list[Clip]] = {channel: [] for channel in DEFAULT_CHANNELS}
        self._is_live = False

        self._build_ui()
        self._wire_signals()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # Fila superior: calendario + conexion (columna angosta) junto a
        # las camaras (todo el espacio restante). La linea de tiempo va
        # DEBAJO de esta fila, a todo lo ancho de la ventana -- por eso no
        # es parte del splitter.
        top_splitter = QSplitter()

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.calendar = CalendarPanel()
        left_layout.addWidget(self.calendar)
        self.connection_panel = ConnectionPanel(self.client.host, self.client.username, self.client.password)
        left_layout.addWidget(self.connection_panel)
        left_layout.addStretch(1)
        top_splitter.addWidget(left_column)

        self.camera_grid = CameraGrid(DEFAULT_CHANNELS)
        top_splitter.addWidget(self.camera_grid)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        root_layout.addWidget(top_splitter, stretch=1)

        self.timeline = TimelineWidget()
        root_layout.addWidget(self.timeline)

        self.status_label = QLabel("Selecciona un dia en el calendario.")
        root_layout.addWidget(self.status_label)

    def _wire_signals(self) -> None:
        self.calendar.day_selected.connect(self._on_day_selected)
        self.timeline.time_selected.connect(self._on_time_selected)

        self.client.clips_ready.connect(self._on_clips_ready)
        self.client.search_failed.connect(self._on_search_failed)
        self.client.frame_ready.connect(self._on_frame_ready)
        self.client.channel_status.connect(self._on_channel_status)

        self.connection_panel.host_input.textChanged.connect(lambda text: setattr(self.client, "host", text))
        self.connection_panel.user_input.textChanged.connect(lambda text: setattr(self.client, "username", text))
        self.connection_panel.password_input.textChanged.connect(lambda text: setattr(self.client, "password", text))
        self.connection_panel.live_toggle_clicked.connect(self._on_live_toggle)

    def _on_day_selected(self, day: date) -> None:
        self.timeline.set_day(day)
        self._clips_by_channel = {channel: [] for channel in DEFAULT_CHANNELS}

        start_dt = datetime.combine(day, dtime.min)
        end_dt = start_dt + timedelta(hours=23, minutes=59, seconds=59)
        self.status_label.setText(f"Buscando grabaciones del {day}...")
        self.client.search(start_dt, end_dt)

    def _on_clips_ready(self, clips: list[Clip]) -> None:
        self._clips_by_channel = {channel: [] for channel in DEFAULT_CHANNELS}
        for clip in clips:
            self._clips_by_channel.setdefault(clip.channel, []).append(clip)

        self.status_label.setText(f"Se encontraron {len(clips)} clips entre los 4 canales.")

    def _on_search_failed(self, message: str) -> None:
        self.status_label.setText(f"Error al buscar grabaciones: {message}")

    def _on_time_selected(self, selected_time: datetime) -> None:
        self.status_label.setText(f"Reproduciendo desde {selected_time:%Y-%m-%d %H:%M:%S}...")
        self.client.play_from(selected_time, self._clips_by_channel)
        self.timeline.start_playhead(selected_time)

    def _on_frame_ready(self, channel: int, frame) -> None:
        panel = self.camera_grid.panels.get(channel)
        if panel is not None:
            panel.set_frame(frame)
        # Libera el freno de backpressure de la vista en vivo para este
        # canal (ver DVRClient._live_channel_worker) -- sin efecto durante
        # reproduccion de grabaciones, que no lo usa.
        self.client.notify_frame_consumed(channel)

    def _on_channel_status(self, channel: int, text: str) -> None:
        panel = self.camera_grid.panels.get(channel)
        if panel is not None:
            panel.set_status(text)

    def _on_live_toggle(self) -> None:
        if self._is_live:
            self.client.stop_live()
            self._is_live = False
            self.connection_panel.set_live_mode(False)
            self.calendar.setEnabled(True)
            self.timeline.setEnabled(True)
            self.status_label.setText("Modo grabaciones.")
        else:
            self.timeline.stop_playhead()
            self.client.stop_playback()
            self._is_live = True
            self.connection_panel.set_live_mode(True)
            self.calendar.setEnabled(False)
            self.timeline.setEnabled(False)
            self.client.start_live()
            self.status_label.setText("Viendo en vivo.")

    def closeEvent(self, event) -> None:
        self.client.stop_playback()
        self.client.stop_live()
        self.timeline.stop_playhead()
        super().closeEvent(event)
