from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from tkinter import BOTH, LEFT, RIGHT, X, Y, Canvas, DoubleVar, Label, StringVar, Tk, messagebox, ttk

try:
    import cv2
    import requests
    from PIL import Image, ImageTk
    from requests.auth import HTTPDigestAuth
except ImportError as exc:  # pragma: no cover - surfaced at startup
    raise SystemExit(f"Missing dependency: {exc}") from exc


try:
    RESAMPLING = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow fallback
    RESAMPLING = Image.LANCZOS


DEFAULT_IP = "192.168.1.108"
DEFAULT_USER = "nancy"
DEFAULT_PASSWORD = "2409"
DEFAULT_CHANNELS = (1, 2, 3, 4)
CHANNEL_COLORS = {
    1: "#60A5FA",
    2: "#34D399",
    3: "#FBBF24",
    4: "#F87171",
}
TIMELINE_LEFT = 96
TIMELINE_RIGHT = 28
TIMELINE_TOP = 24
TIMELINE_LANE_HEIGHT = 30
TIMELINE_LANE_GAP = 0
TIMELINE_AXIS_HEIGHT = 18
PLAYBACK_PANEL_SIZE = (300, 168)


@dataclass(frozen=True)
class Clip:
    channel: int
    start: str
    end: str
    file_size: str = ""

    @property
    def start_dt(self) -> datetime:
        return datetime.strptime(self.start, "%Y-%m-%d %H:%M:%S")

    @property
    def end_dt(self) -> datetime:
        return datetime.strptime(self.end, "%Y-%m-%d %H:%M:%S")

    @property
    def duration(self) -> str:
        delta = self.end_dt - self.start_dt
        total_seconds = max(int(delta.total_seconds()), 0)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class DVRSearchApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Busqueda y visualizacion DVR")
        self.root.geometry("1280x760")
        self.root.minsize(1120, 680)

        self._searching = False
        self._clips_by_channel: dict[int, list[Clip]] = {channel: [] for channel in DEFAULT_CHANNELS}
        self._all_clips: list[Clip] = []
        self._range_start_dt: datetime | None = None
        self._range_end_dt: datetime | None = None
        self._selected_time: datetime | None = None
        self._playback_session = 0
        self._playback_stop_events: dict[int, threading.Event] = {}
        self._latest_frames: dict[int, object | None] = {channel: None for channel in DEFAULT_CHANNELS}
        self._latest_status: dict[int, str] = {channel: "Sin reproduccion" for channel in DEFAULT_CHANNELS}
        self._panel_images: dict[int, object] = {}
        self._timeline_bounds: tuple[int, int, int, int] | None = None
        self._refresh_job = None

        self.ip_var = StringVar(value=DEFAULT_IP)
        self.user_var = StringVar(value=DEFAULT_USER)
        self.password_var = StringVar(value=DEFAULT_PASSWORD)
        self.status_var = StringVar(value="Listo para buscar.")
        self.selected_time_var = StringVar(value="Hora seleccionada: ninguna")
        self.year_var = StringVar()
        self.month_var = StringVar()
        self.day_var = StringVar()
        self.start_minutes_var = DoubleVar(value=0)
        self.end_minutes_var = DoubleVar(value=1439)

        today = date.today()
        self.year_var.set(str(today.year))
        self.month_var.set(f"{today.month:02d}")
        self.day_var.set(f"{today.day:02d}")

        self._build_style()
        self._build_ui()
        self._refresh_day_values()
        self._sync_time_labels()
        self._schedule_refresh()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("App.TFrame", background="#0F172A")
        style.configure("Card.TLabelframe", background="#0F172A", foreground="#E5E7EB")
        style.configure("Card.TLabelframe.Label", background="#0F172A", foreground="#E5E7EB", font=("TkDefaultFont", 10, "bold"))
        style.configure("Section.TLabel", background="#0F172A", foreground="#E5E7EB", font=("TkDefaultFont", 10, "bold"))
        style.configure("Muted.TLabel", background="#0F172A", foreground="#94A3B8")
        style.configure("Status.TLabel", background="#020617", foreground="#E2E8F0", font=("TkDefaultFont", 10, "bold"))
        style.configure("Action.TButton", padding=(12, 8), font=("TkDefaultFont", 10, "bold"))
        style.configure("PlaybackTitle.TLabel", background="#111827", foreground="#E5E7EB", font=("TkDefaultFont", 10, "bold"))
        style.configure("PlaybackStatus.TLabel", background="#111827", foreground="#94A3B8")

    def _build_ui(self) -> None:
        self.root.configure(background="#0F172A")

        outer = ttk.Frame(self.root, padding=8, style="App.TFrame")
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill=X)

        ttk.Label(header, text="Busqueda y visualizacion DVR", style="Section.TLabel").pack(anchor="w")

        timeline_card = ttk.LabelFrame(outer, text="Linea de tiempo", style="Card.TLabelframe", padding=6)
        timeline_card.pack(fill=X, pady=(6, 6))

        self.timeline_canvas = Canvas(
            timeline_card,
            height=TIMELINE_TOP + (TIMELINE_LANE_HEIGHT * 4) + (TIMELINE_LANE_GAP * 3) + TIMELINE_AXIS_HEIGHT + 8,
            bg="#020617",
            highlightthickness=0,
        )
        self.timeline_canvas.pack(fill=X, expand=False)
        self.timeline_canvas.bind("<Button-1>", self._on_timeline_click)
        self.timeline_canvas.bind("<Configure>", lambda _event: self._draw_timeline())

        top_area = ttk.Frame(outer, style="App.TFrame")
        top_area.pack(fill=BOTH, expand=True, pady=(8, 6))

        left_panel = ttk.Frame(top_area, style="App.TFrame", width=340)
        left_panel.pack(side=LEFT, fill=Y)
        left_panel.pack_propagate(False)

        right_panel = ttk.Frame(top_area, style="App.TFrame")
        right_panel.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0))

        search_card = ttk.LabelFrame(left_panel, text="Busqueda", style="Card.TLabelframe", padding=8)
        search_card.pack(fill=X)

        self._build_connection_row(search_card)
        self._build_time_row(search_card)

        actions = ttk.Frame(search_card, style="App.TFrame")
        actions.pack(fill=X, pady=(6, 0))

        self.search_button = ttk.Button(actions, text="Buscar grabaciones", style="Action.TButton", command=self.start_search)
        self.search_button.pack(fill=X)

        self.stop_button = ttk.Button(actions, text="Detener reproduccion", style="Action.TButton", command=self.stop_playback)
        self.stop_button.pack(fill=X, pady=(6, 0))

        ttk.Label(actions, textvariable=self.status_var, style="Muted.TLabel", wraplength=280, justify="left").pack(anchor="w", pady=(6, 0))

        playback_card = ttk.LabelFrame(right_panel, text="Reproduccion embebida", style="Card.TLabelframe", padding=8)
        playback_card.pack(fill=X)

        playback_grid = ttk.Frame(playback_card, style="App.TFrame")
        playback_grid.pack(fill=BOTH, expand=True)

        self.playback_panels: dict[int, dict[str, object]] = {}
        for row in range(2):
            playback_grid.rowconfigure(row, weight=1)
        for column in range(2):
            playback_grid.columnconfigure(column, weight=1)

        for index, channel in enumerate(DEFAULT_CHANNELS):
            container = ttk.Frame(playback_grid, style="App.TFrame", padding=2)
            container.grid(row=index // 2, column=index % 2, sticky="nsew")
            container.columnconfigure(0, weight=1)

            title_row = ttk.Frame(container, style="App.TFrame")
            title_row.pack(fill=X)
            ttk.Label(title_row, text=f"Canal {channel}", style="PlaybackTitle.TLabel").pack(side=LEFT)
            status_var = StringVar(value="Sin reproduccion")
            status_label = ttk.Label(title_row, textvariable=status_var, style="PlaybackStatus.TLabel")
            status_label.pack(side=RIGHT)

            image_label = Label(
                container,
                width=PLAYBACK_PANEL_SIZE[0],
                height=PLAYBACK_PANEL_SIZE[1],
                bg="#020617",
                fg="#94A3B8",
                text="Sin reproduccion",
                compound="center",
                relief="sunken",
                bd=1,
            )
            image_label.pack(fill=BOTH, expand=True, pady=(2, 0))

            self.playback_panels[channel] = {
                "container": container,
                "status_var": status_var,
                "status_widget": status_label,
                "image_label": image_label,
            }

        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill=X, side="bottom")
        ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel", padding=(10, 6)).pack(fill=X)

    def _build_connection_row(self, parent: ttk.Frame) -> None:
        fields = [
            ("IP DVR", self.ip_var, 28, False),
            ("Usuario", self.user_var, 28, False),
            ("Clave", self.password_var, 28, True),
        ]

        for label_text, variable, width, is_secret in fields:
            cell = ttk.Frame(parent, style="App.TFrame")
            cell.pack(fill=X, pady=(0, 5))
            ttk.Label(cell, text=label_text, style="Muted.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=variable, width=width, show="*" if is_secret else "").pack(anchor="w", fill=X, pady=(1, 0))

        date_cell = ttk.Frame(parent, style="App.TFrame")
        date_cell.pack(fill=X, pady=(2, 0))
        ttk.Label(date_cell, text="Fecha", style="Muted.TLabel").pack(anchor="w")

        selector = ttk.Frame(date_cell, style="App.TFrame")
        selector.pack(anchor="w", pady=(1, 0))

        self.year_combo = ttk.Combobox(selector, width=7, textvariable=self.year_var, state="readonly")
        self.month_combo = ttk.Combobox(selector, width=4, textvariable=self.month_var, state="readonly")
        self.day_combo = ttk.Combobox(selector, width=4, textvariable=self.day_var, state="readonly")

        self.year_combo.pack(side=LEFT)
        ttk.Label(selector, text="-", style="Muted.TLabel", padding=(6, 0)).pack(side=LEFT)
        self.month_combo.pack(side=LEFT)
        ttk.Label(selector, text="-", style="Muted.TLabel", padding=(6, 0)).pack(side=LEFT)
        self.day_combo.pack(side=LEFT)

        current_year = date.today().year
        self.year_combo["values"] = [str(current_year - 1), str(current_year), str(current_year + 1)]
        self.month_combo["values"] = [f"{month:02d}" for month in range(1, 13)]
        self.day_combo["values"] = [f"{day:02d}" for day in range(1, 32)]

        self.year_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_day_values())
        self.month_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_day_values())

    def _build_time_row(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill=X, pady=(12, 0))

        start_cell = ttk.Frame(row, style="App.TFrame")
        start_cell.pack(fill=X, expand=True)
        ttk.Label(start_cell, text="Hora inicial", style="Muted.TLabel").pack(anchor="w")
        ttk.Scale(start_cell, from_=0, to=1439, orient="horizontal", command=self._on_time_slider, variable=self.start_minutes_var).pack(fill=X, pady=(2, 0))
        self.start_time_label = ttk.Label(start_cell, text="00:00", style="Section.TLabel")
        self.start_time_label.pack(anchor="w", pady=(1, 0))

        end_cell = ttk.Frame(row, style="App.TFrame")
        end_cell.pack(fill=X, expand=True, padx=(16, 0))
        ttk.Label(end_cell, text="Hora final", style="Muted.TLabel").pack(anchor="w")
        ttk.Scale(end_cell, from_=0, to=1439, orient="horizontal", command=self._on_end_slider, variable=self.end_minutes_var).pack(fill=X, pady=(2, 0))
        self.end_time_label = ttk.Label(end_cell, text="23:59", style="Section.TLabel")
        self.end_time_label.pack(anchor="w", pady=(1, 0))

    def _time_minutes(self, value) -> int:
        try:
            return max(0, min(1439, int(float(value))))
        except ValueError:
            return 0

    def _minutes_to_text(self, minute_value: int) -> str:
        minute_value = max(0, min(1439, int(minute_value)))
        hours, minutes = divmod(minute_value, 60)
        return f"{hours:02d}:{minutes:02d}"

    def _on_time_slider(self, value: str) -> None:
        start_minutes = self._time_minutes(value)
        end_minutes = self._time_minutes(self.end_minutes_var.get())
        if start_minutes > end_minutes:
            end_minutes = start_minutes
            self.end_minutes_var.set(end_minutes)

        self.start_minutes_var.set(start_minutes)
        self._sync_time_labels()

    def _on_end_slider(self, value: str) -> None:
        end_minutes = self._time_minutes(value)
        start_minutes = self._time_minutes(self.start_minutes_var.get())
        if end_minutes < start_minutes:
            start_minutes = end_minutes
            self.start_minutes_var.set(start_minutes)

        self.end_minutes_var.set(end_minutes)
        self._sync_time_labels()

    def _sync_time_labels(self) -> None:
        self.start_time_label.configure(text=self._minutes_to_text(self._time_minutes(self.start_minutes_var.get())))
        self.end_time_label.configure(text=self._minutes_to_text(self._time_minutes(self.end_minutes_var.get())))

    def _refresh_day_values(self) -> None:
        try:
            year = int(self.year_var.get())
            month = int(self.month_var.get())
        except ValueError:
            return

        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        last_day = (next_month - timedelta(days=1)).day
        current_day = self.day_var.get()
        values = [f"{day:02d}" for day in range(1, last_day + 1)]
        self.day_combo["values"] = values
        if current_day not in values:
            self.day_var.set(values[0])

    def _selected_date(self) -> date:
        return date(int(self.year_var.get()), int(self.month_var.get()), int(self.day_var.get()))

    def _selected_range(self) -> tuple[datetime, datetime]:
        selected_date = self._selected_date()
        start_minutes = self._time_minutes(self.start_minutes_var.get())
        end_minutes = self._time_minutes(self.end_minutes_var.get())
        start_dt = datetime.combine(selected_date, datetime.min.time()) + timedelta(minutes=start_minutes)
        end_dt = datetime.combine(selected_date, datetime.min.time()) + timedelta(minutes=end_minutes)
        return start_dt, end_dt

    def start_search(self) -> None:
        if self._searching:
            return

        try:
            start_dt, end_dt = self._selected_range()
        except ValueError:
            messagebox.showerror("Fecha invalida", "Revisa la fecha seleccionada.")
            return

        if start_dt > end_dt:
            messagebox.showerror("Rango invalido", "La hora inicial no puede ser mayor que la final.")
            return

        self._searching = True
        self.search_button.configure(state="disabled")
        self.status_var.set(f"Buscando grabaciones del {start_dt:%Y-%m-%d}...")

        worker = threading.Thread(target=self._search_worker, args=(start_dt, end_dt), daemon=True)
        worker.start()

    def _search_worker(self, start_dt: datetime, end_dt: datetime) -> None:
        clips_by_channel: dict[int, list[Clip]] = {channel: [] for channel in DEFAULT_CHANNELS}
        error_message: str | None = None

        try:
            for channel in DEFAULT_CHANNELS:
                clips_by_channel[channel] = self._fetch_clips(channel, start_dt, end_dt)
        except Exception as exc:
            error_message = str(exc)

        def finish() -> None:
            self._searching = False
            self.search_button.configure(state="normal")

            if error_message:
                self.status_var.set("Error al buscar grabaciones.")
                messagebox.showerror("Busqueda fallida", error_message)
                self._clips_by_channel = {channel: [] for channel in DEFAULT_CHANNELS}
                self._all_clips = []
            else:
                self._clips_by_channel = clips_by_channel
                self._all_clips = [clip for channel in DEFAULT_CHANNELS for clip in clips_by_channel[channel]]
                self.status_var.set(f"Se encontraron {len(self._all_clips)} clips entre los 4 canales.")

            self._range_start_dt = start_dt
            self._range_end_dt = end_dt
            self._selected_time = None
            self.selected_time_var.set("Hora seleccionada: ninguna")
            self.stop_playback(clear_message=False)
            self._draw_timeline()

        self.root.after(0, finish)

    def _fetch_clips(self, channel: int, start_dt: datetime, end_dt: datetime) -> list[Clip]:
        auth = HTTPDigestAuth(self.user_var.get().strip(), self.password_var.get())
        ip_dvr = self.ip_var.get().strip()

        url_create = f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=factory.create"
        response = requests.get(url_create, auth=auth, timeout=15)
        match = re.search(r"result=(\d+)", response.text)
        if not match:
            raise RuntimeError("No se pudo iniciar la sesion de busqueda en el DVR.")

        object_id = match.group(1).strip()
        clips: list[Clip] = []

        try:
            start_query = start_dt.strftime("%Y-%m-%d%%20%H:%M:%S")
            end_query = end_dt.strftime("%Y-%m-%d%%20%H:%M:%S")

            url_find = (
                f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=findFile&object={object_id}"
                f"&condition.Channel={channel}&condition.StartTime={start_query}&condition.EndTime={end_query}"
            )
            requests.get(url_find, auth=auth, timeout=15)

            url_results = f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={object_id}&count=200"
            results = requests.get(url_results, auth=auth, timeout=15)

            for _index, item in self._parse_items(results.text).items():
                start = item.get("StartTime")
                end = item.get("EndTime")
                if start and end:
                    clips.append(
                        Clip(
                            channel=channel,
                            start=start.strip(),
                            end=end.strip(),
                            file_size=item.get("FileSize", "").strip(),
                        )
                    )
        finally:
            url_close = f"http://{ip_dvr}/cgi-bin/mediaFileFind.cgi?action=destroy&object={object_id}"
            try:
                requests.get(url_close, auth=auth, timeout=10)
            except Exception:
                pass

        return clips

    def _parse_items(self, payload: str) -> dict[int, dict[str, str]]:
        items: dict[int, dict[str, str]] = {}
        pattern = re.compile(r"items\[(\d+)\]\.([A-Za-z0-9_]+)=(.*)")

        for line in payload.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue

            index = int(match.group(1))
            key = match.group(2)
            value = match.group(3).strip()
            items.setdefault(index, {})[key] = value

        return items

    def _draw_timeline(self) -> None:
        canvas = self.timeline_canvas
        canvas.delete("all")
        self._timeline_bounds = None

        if self._range_start_dt is None or self._range_end_dt is None:
            canvas.create_text(20, 30, anchor="w", fill="#94A3B8", text="Busca grabaciones para ver la linea de tiempo.")
            return

        width = max(canvas.winfo_width(), 900)
        timeline_width = max(width - TIMELINE_LEFT - TIMELINE_RIGHT, 600)
        top = TIMELINE_TOP
        lane_height = TIMELINE_LANE_HEIGHT
        gap = TIMELINE_LANE_GAP
        self._timeline_bounds = (TIMELINE_LEFT, top, TIMELINE_LEFT + timeline_width, top + (lane_height * 4) + (gap * 3))
        canvas.configure(height=TIMELINE_TOP + (lane_height * 4) + (gap * 3) + TIMELINE_AXIS_HEIGHT + 12)

        canvas.create_rectangle(TIMELINE_LEFT, top, TIMELINE_LEFT + timeline_width, top + (lane_height * 4) + (gap * 3), fill="#0B1120", outline="#1F2937")
        canvas.create_text(18, top + 8, anchor="w", fill="#E5E7EB", text="Canal 1")
        canvas.create_text(18, top + lane_height + gap + 8, anchor="w", fill="#E5E7EB", text="Canal 2")
        canvas.create_text(18, top + (lane_height + gap) * 2 + 8, anchor="w", fill="#E5E7EB", text="Canal 3")
        canvas.create_text(18, top + (lane_height + gap) * 3 + 8, anchor="w", fill="#E5E7EB", text="Canal 4")

        for channel in DEFAULT_CHANNELS:
            lane_top = top + (channel - 1) * (lane_height + gap)
            lane_bottom = lane_top + lane_height
            canvas.create_rectangle(TIMELINE_LEFT, lane_top, TIMELINE_LEFT + timeline_width, lane_bottom, fill="#111827", outline="#1F2937")

        self._draw_time_axis(timeline_width)

        for channel in DEFAULT_CHANNELS:
            self._draw_channel_clips(channel, timeline_width)

        if self._selected_time is not None:
            self._draw_selected_marker(timeline_width)

    def _draw_time_axis(self, timeline_width: int) -> None:
        canvas = self.timeline_canvas
        start_dt = self._range_start_dt
        end_dt = self._range_end_dt
        if start_dt is None or end_dt is None:
            return

        axis_y = TIMELINE_TOP + (TIMELINE_LANE_HEIGHT * 4) + (TIMELINE_LANE_GAP * 3) + 6
        total_minutes = max(int((end_dt - start_dt).total_seconds() // 60), 1)
        step = 30 if total_minutes > 180 else 15
        for minute in range(0, total_minutes + 1, step):
            current = start_dt + timedelta(minutes=minute)
            x = TIMELINE_LEFT + int((minute / total_minutes) * timeline_width)
            canvas.create_line(x, axis_y - 4, x, axis_y + 8, fill="#475569")
            canvas.create_text(x, axis_y + 12, fill="#94A3B8", text=current.strftime("%H:%M"), anchor="n")

    def _draw_channel_clips(self, channel: int, timeline_width: int) -> None:
        canvas = self.timeline_canvas
        start_dt = self._range_start_dt
        end_dt = self._range_end_dt
        if start_dt is None or end_dt is None:
            return

        lane_top = TIMELINE_TOP + (channel - 1) * (TIMELINE_LANE_HEIGHT + TIMELINE_LANE_GAP)
        lane_bottom = lane_top + TIMELINE_LANE_HEIGHT
        total_seconds = max((end_dt - start_dt).total_seconds(), 1)

        for clip in self._clips_by_channel.get(channel, []):
            visible_start = max(clip.start_dt, start_dt)
            visible_end = min(clip.end_dt, end_dt)
            if visible_start >= visible_end:
                continue

            x1 = TIMELINE_LEFT + int(((visible_start - start_dt).total_seconds() / total_seconds) * timeline_width)
            x2 = TIMELINE_LEFT + int(((visible_end - start_dt).total_seconds() / total_seconds) * timeline_width)
            x2 = max(x2, x1 + 4)

            canvas.create_rectangle(
                x1,
                lane_top,
                x2,
                lane_bottom,
                fill=CHANNEL_COLORS.get(channel, "#64748B"),
                outline="#E2E8F0",
                width=1,
                tags=(f"clip-{channel}",),
            )
            if x2 - x1 > 72:
                canvas.create_text(x1 + 6, lane_top + 16, anchor="w", fill="#0F172A", text=f"{clip.start_dt:%H:%M} - {clip.end_dt:%H:%M}")

    def _draw_selected_marker(self, timeline_width: int) -> None:
        if self._selected_time is None or self._range_start_dt is None or self._range_end_dt is None:
            return

        total_seconds = max((self._range_end_dt - self._range_start_dt).total_seconds(), 1)
        selected_seconds = (self._selected_time - self._range_start_dt).total_seconds()
        selected_seconds = max(0, min(total_seconds, selected_seconds))
        x = TIMELINE_LEFT + int((selected_seconds / total_seconds) * timeline_width)

        marker_top = TIMELINE_TOP - 4
        marker_bottom = TIMELINE_TOP + (TIMELINE_LANE_HEIGHT * 4) + (TIMELINE_LANE_GAP * 3)
        self.timeline_canvas.create_line(x, marker_top, x, marker_bottom, fill="#F8FAFC", width=2)
        self.timeline_canvas.create_oval(x - 5, marker_top - 5, x + 5, marker_top + 5, fill="#F8FAFC", outline="#F8FAFC")

    def _on_timeline_click(self, event) -> None:
        if self._range_start_dt is None or self._range_end_dt is None:
            return

        bounds = self._timeline_bounds
        if bounds is None:
            return

        left, _top, right, _bottom = bounds
        x = max(left, min(right, event.x))
        total_seconds = max((self._range_end_dt - self._range_start_dt).total_seconds(), 1)
        ratio = (x - left) / max(right - left, 1)
        selected_seconds = int(total_seconds * ratio)
        self._selected_time = self._range_start_dt + timedelta(seconds=selected_seconds)
        self.selected_time_var.set(f"Hora seleccionada: {self._selected_time:%Y-%m-%d %H:%M:%S}")
        self._draw_timeline()
        self.start_playback(self._selected_time)

    def start_playback(self, selected_time: datetime) -> None:
        self.stop_playback(clear_message=False)
        self._selected_time = selected_time
        self.selected_time_var.set(f"Hora seleccionada: {selected_time:%Y-%m-%d %H:%M:%S}")
        self.status_var.set("Preparando reproduccion de los 4 canales...")

        self._playback_session += 1
        session_id = self._playback_session
        self._playback_stop_events = {channel: threading.Event() for channel in DEFAULT_CHANNELS}

        for channel in DEFAULT_CHANNELS:
            worker = threading.Thread(
                target=self._play_channel_worker,
                args=(session_id, channel, selected_time, self._playback_stop_events[channel]),
                daemon=True,
            )
            worker.start()

        self._draw_timeline()

    def stop_playback(self, clear_message: bool = True) -> None:
        for event in self._playback_stop_events.values():
            event.set()

        self._playback_stop_events = {}
        self._latest_frames = {channel: None for channel in DEFAULT_CHANNELS}
        self._latest_status = {channel: "Sin reproduccion" for channel in DEFAULT_CHANNELS}
        for channel in DEFAULT_CHANNELS:
            panel = self.playback_panels[channel]
            image_label: Label = panel["image_label"]  # type: ignore[assignment]
            image_label.configure(image="", text="Sin reproduccion")
            image_label.image = None
            status_widget: ttk.Label = panel["status_widget"]  # type: ignore[assignment]
            status_widget.configure(text="Sin reproduccion")

        if clear_message:
            self.status_var.set("Reproduccion detenida.")

    def _find_clip_for_time(self, channel: int, selected_time: datetime) -> Clip | None:
        for clip in self._clips_by_channel.get(channel, []):
            if clip.start_dt <= selected_time <= clip.end_dt:
                return clip
        return None

    def _play_channel_worker(self, session_id: int, channel: int, selected_time: datetime, stop_event: threading.Event) -> None:
        clip = self._find_clip_for_time(channel, selected_time)
        if clip is None:
            self._latest_status[channel] = "Sin grabacion en esa hora"
            return

        start_time = max(clip.start_dt, selected_time)
        end_time = clip.end_dt

        ip_dvr = self.ip_var.get().strip()
        user = self.user_var.get().strip()
        password = self.password_var.get()

        start_query = start_time.strftime("%Y-%m-%d%%20%H:%M:%S")
        end_query = end_time.strftime("%Y-%m-%d%%20%H:%M:%S")
        url = (
            f"http://{user}:{password}@{ip_dvr}/cgi-bin/loadfile.cgi?action=startLoad"
            f"&channel={channel}&startTime={start_query}&endTime={end_query}"
        )

        self._latest_status[channel] = f"Cargando {start_time:%H:%M:%S}"
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            self._latest_status[channel] = "No se pudo abrir la grabacion"
            return

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0 or not fps < float("inf"):
            fps = 25.0
        frame_interval = 1.0 / fps
        next_frame_at = time.monotonic()

        try:
            while not stop_event.is_set() and session_id == self._playback_session:
                now = time.monotonic()
                if now < next_frame_at:
                    time.sleep(next_frame_at - now)

                success, frame = capture.read()
                if not success:
                    break
                self._latest_frames[channel] = frame
                self._latest_status[channel] = f"Reproduciendo {start_time:%H:%M:%S}"
                next_frame_at = max(next_frame_at + frame_interval, time.monotonic())
        finally:
            capture.release()
            if session_id == self._playback_session and not stop_event.is_set():
                self._latest_status[channel] = "Fin de segmento"

    def _frame_to_photo(self, frame) -> object:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image = image.resize(PLAYBACK_PANEL_SIZE, RESAMPLING)
        return ImageTk.PhotoImage(image)

    def _schedule_refresh(self) -> None:
        self._refresh_panels()
        self._refresh_job = self.root.after(60, self._schedule_refresh)

    def _refresh_panels(self) -> None:
        for channel in DEFAULT_CHANNELS:
            panel = self.playback_panels[channel]
            image_label: Label = panel["image_label"]  # type: ignore[assignment]
            status_var: StringVar = panel["status_var"]  # type: ignore[assignment]

            status_var.set(self._latest_status.get(channel, "Sin reproduccion"))
            frame = self._latest_frames.get(channel)
            if frame is None:
                continue

            try:
                photo = self._frame_to_photo(frame)
            except Exception:
                continue

            self._panel_images[channel] = photo
            image_label.configure(image=photo, text="")
            image_label.image = photo

    def _on_close(self) -> None:
        self.stop_playback(clear_message=False)
        if self._refresh_job is not None:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
        self.root.destroy()


def main() -> None:
    root = Tk()
    DVRSearchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
