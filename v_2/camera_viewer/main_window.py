from __future__ import annotations

import os
from datetime import date, datetime, time as dtime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from .calendar_panel import CalendarPanel
from .camera_grid import CameraGrid
from .connection_panel import ConnectionPanel
from .dvr_info_dialog import DvrInfoDialog
from .playback_controls import JUMP_SECONDS, PlaybackControls
from .dvr_client import Clip, DEFAULT_CHANNELS, DVRClient, LIVE_TO_RECORDINGS_SETTLE
from .light_query_manager import LightPriority
from .timeline_widget import TimelineWidget


RECORDINGS_HINT = "Selecciona una hora en la línea de tiempo"

# Cada cuanto, en vista en vivo, se vuelven a pedir los clips de hoy (para que
# los minutos recientes dejen de verse como "sin grabacion") y se re-sincroniza
# el cursor con la hora real.
LIVE_TOOLS_REFRESH_MS = 60_000
PLAYHEAD_REFRESH_MS = 100


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Visor de cámaras")
        self.resize(1400, 900)

        self.client = DVRClient(self)
        self._clips_by_channel: dict[int, list[Clip]] = {channel: [] for channel in DEFAULT_CHANNELS}
        self._is_live = False
        # Mientras es False se descartan los frames/estados de grabaciones que
        # lleguen (las señales entre hilos se encolan): un frame viejo que
        # llegara justo despues de limpiar los paneles los dejaria
        # "congelados" otra vez. Se activa al arrancar una reproduccion.
        self._accept_recording_output = False

        # F11 alterna pantalla completa (entrar Y salir con la misma tecla).
        # La app siempre abre en ventana normal: no se recuerda el estado.
        self._maximized_before_fullscreen = False
        self._fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)

        # Atajos de la reproducción: solo activos mientras hay una (así no le
        # quitan las flechas al calendario ni el espacio a los campos de texto).
        self._pause_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._pause_shortcut.activated.connect(self._toggle_pause)
        self._back_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._back_shortcut.activated.connect(lambda: self._jump(-JUMP_SECONDS))
        self._forward_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._forward_shortcut.activated.connect(lambda: self._jump(JUMP_SECONDS))

        # El cursor de la línea de tiempo en grabaciones sigue el reloj compartido de la
        # reproducción (client.control), no uno propio: así coincide con el video.
        self._playhead_timer = QTimer(self)
        self._playhead_timer.setInterval(PLAYHEAD_REFRESH_MS)
        self._playhead_timer.timeout.connect(self._update_playhead)

        self._live_tools_timer = QTimer(self)
        self._live_tools_timer.setInterval(LIVE_TOOLS_REFRESH_MS)
        self._live_tools_timer.timeout.connect(self._refresh_live_tools)

        self._build_ui()
        self._wire_signals()

        # El calendario ya arranca con hoy seleccionado (pastilla azul) pero
        # eso no dispara day_selected -- se pide a mano lo mismo que haria un
        # clic en ese dia, para que la linea de tiempo y sus clips ya esten
        # listos al abrir la app. Solo se selecciona y se cargan los clips:
        # no arranca reproduccion sola, el usuario elige la hora.
        self._on_day_selected(self.calendar.selected_date())

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
        # Recordatorio del atajo, al fondo de la columna: tenue a proposito
        # (no es un control, solo una pista) y con las menos palabras posibles.
        fullscreen_hint = QLabel("F11: pantalla completa")
        fullscreen_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fullscreen_hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        left_layout.addWidget(fullscreen_hint)
        top_splitter.addWidget(left_column)

        # Un CameraGrid distinto por modo (no uno solo compartido): vivo
        # pide el substream de baja resolucion y grabaciones reproduce el
        # archivo a su resolucion original -- con un solo grid, cambiar de
        # modo dejaba el zoom/encaje de cada panel calculado contra el
        # tamaño de frame del modo anterior, produciendo un recorte
        # incorrecto hasta que se le hacia zoom a mano de nuevo. Con grids
        # separados cada uno tiene su propio estado de zoom/pan siempre
        # consistente con lo que en verdad esta mostrando.
        self.live_camera_grid = CameraGrid(DEFAULT_CHANNELS, initial_status="Conectando en vivo...")
        self.recordings_camera_grid = CameraGrid(DEFAULT_CHANNELS, initial_status=RECORDINGS_HINT)
        self.camera_grid_stack = QStackedWidget()
        self.camera_grid_stack.addWidget(self.recordings_camera_grid)
        self.camera_grid_stack.addWidget(self.live_camera_grid)
        top_splitter.addWidget(self.camera_grid_stack)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        root_layout.addWidget(top_splitter, stretch=1)

        self.playback_controls = PlaybackControls()
        root_layout.addWidget(self.playback_controls)
        self._set_playback_active(False)

        self.timeline = TimelineWidget()
        root_layout.addWidget(self.timeline)

        self.status_label = QLabel("Selecciona un día en el calendario.")
        root_layout.addWidget(self.status_label)

    def _wire_signals(self) -> None:
        self.calendar.day_selected.connect(self._on_day_selected)
        self.calendar.month_changed.connect(self._on_calendar_month_changed)
        self.timeline.time_selected.connect(self._on_time_selected)
        self.connection_panel.info_clicked.connect(self._show_dvr_info)
        self.playback_controls.pause_clicked.connect(self._toggle_pause)
        self.playback_controls.jump_clicked.connect(self._jump)
        self.playback_controls.reverse_toggled.connect(self._set_reverse)
        self.playback_controls.speed_selected.connect(self._set_speed)

        self.client.clips_ready.connect(self._on_clips_ready)
        self.client.search_failed.connect(self._on_search_failed)
        self.client.recording_frame_ready.connect(self._on_recording_frame_ready)
        self.client.recording_channel_status.connect(self._on_recording_channel_status)
        self.client.live_frame_ready.connect(self._on_live_frame_ready)
        self.client.live_channel_status.connect(self._on_live_channel_status)
        self.client.recorded_days_ready.connect(self.calendar.set_recorded_days)
        self.client.recorded_days_failed.connect(self._on_recorded_days_failed)
        self.client.playback_day_changed.connect(self._on_playback_day_changed)

        # El calendario ya calculo su mes inicial durante su propio
        # __init__, antes de que esta conexion existiera -- esa primera
        # emision de month_changed se perdio, asi que hay que pedir los
        # dias con grabacion del mes ya mostrado una vez a mano aqui.
        self._on_calendar_month_changed(*self.calendar.current_page())

        self.connection_panel.host_input.textChanged.connect(lambda text: setattr(self.client, "host", text))
        self.connection_panel.user_input.textChanged.connect(lambda text: setattr(self.client, "username", text))
        self.connection_panel.password_input.textChanged.connect(lambda text: setattr(self.client, "password", text))
        self.connection_panel.live_toggle_clicked.connect(self._on_live_toggle)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            # Vuelve a como estaba antes: maximizada o normal (showNormal()
            # a secas dejaria en "normal" una ventana que estaba maximizada).
            if self._maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self._maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()

    def _on_day_selected(self, day: date) -> None:
        # Un clic del usuario en el calendario (o el arranque de la app). En
        # vista en vivo equivale a pedir grabaciones de ese dia: se sale de
        # vivo y, como en cualquier cambio de dia, los paneles vuelven al
        # aviso de elegir una hora -- no se reproduce nada solo.
        if self._is_live:
            self._exit_live()
        self._reset_recordings_view()
        self._load_day(day)

    def _load_day(self, day: date) -> None:
        self.timeline.set_day(day)
        self._clips_by_channel = {channel: [] for channel in DEFAULT_CHANNELS}
        self._request_clips(day)

    def _request_clips(self, day: date, priority: int = LightPriority.USER) -> None:
        start_dt = datetime.combine(day, dtime.min)
        end_dt = start_dt + timedelta(hours=23, minutes=59, seconds=59)
        if not self._is_live:
            self.status_label.setText(f"Buscando grabaciones del {day}...")
        self.client.search(start_dt, end_dt, priority)

    def _show_dvr_info(self) -> None:
        DvrInfoDialog(self.client.host, self.client.username, self.client.password, self._is_live, self).exec()

    def _set_playback_active(self, active: bool) -> None:
        """Los controles de reproducción (barra y atajos) solo están activos
        mientras hay una reproducción de grabaciones en curso."""
        self.playback_controls.set_active(active)
        self.playback_controls.set_paused(self.client.control.paused if active else False)
        self.playback_controls.set_reverse(self.client.control.reverse if active else False)
        self.playback_controls.set_speed(self.client.control.speed)
        for shortcut in (self._pause_shortcut, self._back_shortcut, self._forward_shortcut):
            shortcut.setEnabled(active)

    def _toggle_pause(self) -> None:
        paused = self.client.toggle_pause()
        self.playback_controls.set_paused(paused)

    def _jump(self, seconds: int) -> None:
        """Salta ±seconds desde donde va el cursor, sin reiniciar la reproducción
        (ver DVRClient.seek). Conserva la pausa: en pausa se ve el primer
        cuadro del punto nuevo y sigue en pausa."""
        current = self.client.control.media_now()
        day = self.timeline.day
        if current is None or day is None or self._is_live:
            return
        day_start = datetime.combine(day, dtime.min)
        target = min(max(current + timedelta(seconds=seconds), day_start), day_start + timedelta(hours=23, minutes=59, seconds=59))
        self._accept_recording_output = True
        self.client.seek(target)
        self.timeline.draw_playhead(target)

    def _update_playhead(self) -> None:
        if self._is_live or not self.client.playback_active:
            return
        moment = self.client.control.media_now()
        if moment is not None:
            self.timeline.draw_playhead(moment)

    def _set_speed(self, speed: float) -> None:
        self.client.set_speed(speed)
        self.playback_controls.set_speed(speed)

    def _set_reverse(self, reverse: bool) -> None:
        self.client.set_reverse(reverse)
        self.playback_controls.set_reverse(reverse)

    def _reset_recordings_view(self) -> None:
        """Detiene cualquier reproduccion y deja los paneles de grabaciones
        como nuevos, con el aviso de elegir una hora."""
        self.client.stop_playback()
        self._playhead_timer.stop()
        self.timeline.stop_playhead()
        self.timeline.clear_marker()
        self._accept_recording_output = False
        self._set_playback_active(False)
        self.recordings_camera_grid.reset(RECORDINGS_HINT)

    def _on_clips_ready(self, clips: list[Clip]) -> None:
        self._clips_by_channel = {channel: [] for channel in DEFAULT_CHANNELS}
        for clip in clips:
            self._clips_by_channel.setdefault(clip.channel, []).append(clip)

        self.timeline.set_clips(self._clips_by_channel)
        if not self._is_live:
            self.status_label.setText(f"Se encontraron {len(clips)} clips entre los 4 canales.")

    def _on_search_failed(self, message: str) -> None:
        self.status_label.setText(f"Error al buscar grabaciones: {message}")

    def _on_calendar_month_changed(self, year: int, month: int) -> None:
        self.client.find_recorded_days(year, month)

    def _on_recorded_days_failed(self, message: str) -> None:
        self.status_label.setText(f"Error al consultar días con grabación: {message}")

    def _on_time_selected(self, selected_time: datetime) -> None:
        # En vista en vivo, un clic en la línea de tiempo equivale a "ver
        # grabaciones desde ahí": se sale de vivo y se reproduce desde la hora
        # elegida, tras una breve espera para que el DVR libere los RTSP.
        start_delay = 0.0
        if self._is_live:
            self._exit_live()
            start_delay = LIVE_TO_RECORDINGS_SETTLE

        self._accept_recording_output = True
        self.status_label.setText(f"Reproduciendo desde {selected_time:%Y-%m-%d %H:%M:%S}...")
        if self.client.playback_active:
            # Ya hay una reproducción de este día: se salta dentro de ella (usa
            # los bloques que ya están en disco; solo descarga lo que falte).
            self.client.seek(selected_time, resume=True)
        else:
            self.client.play_from(selected_time, self._clips_by_channel, start_delay=start_delay)
        self.timeline.draw_playhead(selected_time)
        self._playhead_timer.start()
        self._set_playback_active(True)

    def _on_playback_day_changed(self, day: date) -> None:
        """La reproduccion cruzo la medianoche: calendario y linea de tiempo
        pasan al dia nuevo y el cursor sigue desde las 00:00:00, sin tocar los
        paneles (la reproduccion no se interrumpe). Lo emite cada canal al
        cruzar, asi que los repetidos se ignoran."""
        if self._is_live or self.timeline.day == day:
            return
        self.calendar.select_date(day)
        self._load_day(day)  # el cursor reaparece solo: el reloj compartido ya sigue en el día nuevo

    def _on_recording_frame_ready(self, channel: int, frame) -> None:
        if not self._accept_recording_output:
            return
        panel = self.recordings_camera_grid.panels.get(channel)
        if panel is not None:
            panel.set_frame(frame)
        # Libera el freno de backpressure de la reproduccion de grabaciones
        # para este canal (ver ChannelPlayer._play_entry).
        self.client.notify_recording_frame_consumed(channel)

    def _on_recording_channel_status(self, channel: int, text: str) -> None:
        if not self._accept_recording_output:
            return
        panel = self.recordings_camera_grid.panels.get(channel)
        if panel is not None:
            panel.set_status(text)

    def _on_live_frame_ready(self, channel: int, frame) -> None:
        panel = self.live_camera_grid.panels.get(channel)
        if panel is not None:
            panel.set_frame(frame)
        # Libera el freno de backpressure de la vista en vivo para este canal
        # (ver DVRClient._live_channel_worker).
        self.client.notify_frame_consumed(channel)

    def _on_live_channel_status(self, channel: int, text: str) -> None:
        panel = self.live_camera_grid.panels.get(channel)
        if panel is not None:
            panel.set_status(text)

    def _on_live_toggle(self) -> None:
        if self._is_live:
            self._exit_live()
        else:
            self._enter_live()

    def _enter_live(self) -> None:
        # Los paneles de grabaciones se limpian aqui (no al volver): así al
        # regresar no queda ningun frame viejo "congelado".
        self._reset_recordings_view()
        self._is_live = True
        self.camera_grid_stack.setCurrentWidget(self.live_camera_grid)
        self.playback_controls.setVisible(False)
        self.connection_panel.set_live_mode(True)
        # Calendario y linea de tiempo NO se deshabilitan: acompañan a la
        # vista en vivo (hoy seleccionado, cursor avanzando con la hora
        # real) y un clic en cualquiera de los dos sale de vivo.
        self._sync_tools_to_live_clock()
        self._live_tools_timer.start()
        self.client.start_live()
        self.status_label.setText("Viendo en vivo.")

    def _exit_live(self) -> None:
        self._live_tools_timer.stop()
        self.client.stop_live()
        self._is_live = False
        self.timeline.stop_playhead()
        self.timeline.clear_marker()
        self.camera_grid_stack.setCurrentWidget(self.recordings_camera_grid)
        self.playback_controls.setVisible(True)
        self.connection_panel.set_live_mode(False)
        self.status_label.setText("Modo grabaciones.")

    def _sync_tools_to_live_clock(self, priority: int = LightPriority.USER) -> None:
        """Calendario en hoy y cursor de la línea de tiempo en la hora real
        (los frames en vivo son "lo último disponible"), avanzando segundo a
        segundo. Si la línea de tiempo ya muestra hoy solo se refrescan sus
        clips, sin borrarla ni reiniciar su zoom."""
        now = datetime.now()
        today = now.date()
        page_before = self.calendar.current_page()
        self.calendar.select_date(today)
        if self.timeline.day != today:
            self._load_day(today)
            # Si cambio de mes el calendario ya pidio sus dias con
            # grabacion por su cuenta (month_changed); si no (p. ej. el
            # cambio de dia a medianoche) hay que pedirlos aqui.
            if self.calendar.current_page() == page_before:
                self.client.find_recorded_days(today.year, today.month)
        else:
            self._request_clips(today, priority)
        self.timeline.start_playhead(now)

    def _refresh_live_tools(self) -> None:
        if not self._is_live:
            self._live_tools_timer.stop()
            return
        # Tambien cubre el cambio de dia (medianoche) estando en vivo.
        self._sync_tools_to_live_clock(LightPriority.PERIODIC)

    def closeEvent(self, event) -> None:
        self.client.stop_playback()
        self.client.stop_live()
        self.timeline.stop_playhead()
        super().closeEvent(event)

        # Cierre forzado del proceso: se observaron instancias que, tras
        # cerrar la ventana, seguian vivas de fondo consumiendo CPU/RAM (el
        # hilo de la GUI puede quedar atascado detras de una cola de frames
        # pendiente, o QApplication tarda en notar que ya no hay ventanas
        # visibles). Para esta app, cerrar la ventana SIEMPRE debe terminar
        # el proceso -- los hilos de red ya se detuvieron arriba, asi que
        # cortar aqui es seguro.
        os._exit(0)
