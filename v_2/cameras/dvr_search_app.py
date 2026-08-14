from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import date, datetime
from tkinter import BOTH, LEFT, RIGHT, X, Y, DoubleVar, StringVar, Tk, messagebox, ttk

try:
    import cv2
    import requests
    from requests.auth import HTTPDigestAuth
except ImportError as exc:  # pragma: no cover - dependency issue is surfaced at startup
    raise SystemExit(f"Missing dependency: {exc}") from exc


DEFAULT_IP = "192.168.1.108"
DEFAULT_USER = "nancy"
DEFAULT_PASSWORD = "2409"
DEFAULT_CHANNELS = (1, 2, 3, 4)


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
        self.root.geometry("1280x780")
        self.root.minsize(1100, 700)

        self._searching = False
        self._all_clips: list[Clip] = []
        self._selected_channel = 0

        self.ip_var = StringVar(value=DEFAULT_IP)
        self.user_var = StringVar(value=DEFAULT_USER)
        self.password_var = StringVar(value=DEFAULT_PASSWORD)
        self.status_var = StringVar(value="Listo para buscar.")
        self.count_vars = {channel: StringVar(value="0 clips") for channel in DEFAULT_CHANNELS}
        self.start_minutes_var = DoubleVar(value=0)
        self.end_minutes_var = DoubleVar(value=1439)

        today = date.today()
        self.year_var = StringVar(value=str(today.year))
        self.month_var = StringVar(value=f"{today.month:02d}")
        self.day_var = StringVar(value=f"{today.day:02d}")

        self._build_style()
        self._build_ui()
        self._refresh_day_values()
        self._sync_time_labels()

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("App.TFrame", background="#111827")
        style.configure("Card.TLabelframe", background="#111827", foreground="#E5E7EB")
        style.configure("Card.TLabelframe.Label", background="#111827", foreground="#E5E7EB", font=("TkDefaultFont", 10, "bold"))
        style.configure("Section.TLabel", background="#111827", foreground="#E5E7EB", font=("TkDefaultFont", 10, "bold"))
        style.configure("Muted.TLabel", background="#111827", foreground="#9CA3AF")
        style.configure("Status.TLabel", background="#0F172A", foreground="#E5E7EB", font=("TkDefaultFont", 10, "bold"))
        style.configure("Channel.TButton", padding=(14, 10), font=("TkDefaultFont", 10, "bold"))
        style.configure("ChannelSelected.TButton", padding=(14, 10), font=("TkDefaultFont", 10, "bold"), background="#2563EB", foreground="white")
        style.map("ChannelSelected.TButton", foreground=[("active", "white")], background=[("active", "#1D4ED8")])
        style.configure("Action.TButton", padding=(12, 8), font=("TkDefaultFont", 10, "bold"))

    def _build_ui(self) -> None:
        self.root.configure(background="#111827")

        outer = ttk.Frame(self.root, padding=16, style="App.TFrame")
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill=X)

        title = ttk.Label(header, text="Busqueda y visualizacion DVR", style="Section.TLabel")
        title.pack(anchor="w")

        subtitle = ttk.Label(
            header,
            text="Busca grabaciones por fecha y hora, filtra por canal y reproduce el clip elegido.",
            style="Muted.TLabel",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        search_card = ttk.LabelFrame(outer, text="Busqueda", style="Card.TLabelframe", padding=14)
        search_card.pack(fill=X, pady=(14, 12))

        self._build_connection_row(search_card)
        self._build_date_row(search_card)

        actions_row = ttk.Frame(search_card, style="App.TFrame")
        actions_row.pack(fill=X, pady=(12, 0))

        self.search_button = ttk.Button(actions_row, text="Buscar grabaciones", style="Action.TButton", command=self.start_search)
        self.search_button.pack(side=LEFT)

        self.play_button = ttk.Button(actions_row, text="Reproducir seleccionado", style="Action.TButton", command=self.play_selected_clip)
        self.play_button.pack(side=LEFT, padx=(10, 0))

        self.clear_button = ttk.Button(actions_row, text="Limpiar filtro", style="Action.TButton", command=self.clear_filter)
        self.clear_button.pack(side=LEFT, padx=(10, 0))

        self.searching_label = ttk.Label(actions_row, textvariable=self.status_var, style="Muted.TLabel")
        self.searching_label.pack(side=RIGHT)

        channels_card = ttk.LabelFrame(outer, text="Canales 1 a 4", style="Card.TLabelframe", padding=14)
        channels_card.pack(fill=X, pady=(0, 12))

        self.channel_buttons: dict[int, ttk.Button] = {}
        channels_row = ttk.Frame(channels_card, style="App.TFrame")
        channels_row.pack(fill=X)
        for channel in DEFAULT_CHANNELS:
            button = ttk.Button(
                channels_row,
                text=self._channel_button_text(channel),
                style="Channel.TButton",
                command=lambda current=channel: self.select_channel(current),
            )
            button.pack(side=LEFT, expand=True, fill=X, padx=(0, 10) if channel != DEFAULT_CHANNELS[-1] else 0)
            self.channel_buttons[channel] = button

        results_card = ttk.LabelFrame(outer, text="Grabaciones encontradas", style="Card.TLabelframe", padding=12)
        results_card.pack(fill=BOTH, expand=True)

        tree_frame = ttk.Frame(results_card, style="App.TFrame")
        tree_frame.pack(fill=BOTH, expand=True)

        columns = ("canal", "inicio", "fin", "duracion", "tamano")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse", height=14)
        self.tree.heading("canal", text="Canal")
        self.tree.heading("inicio", text="Inicio")
        self.tree.heading("fin", text="Fin")
        self.tree.heading("duracion", text="Duracion")
        self.tree.heading("tamano", text="Tamanio")
        self.tree.column("canal", width=70, anchor="center")
        self.tree.column("inicio", width=220, anchor="w")
        self.tree.column("fin", width=220, anchor="w")
        self.tree.column("duracion", width=100, anchor="center")
        self.tree.column("tamano", width=110, anchor="e")
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda _event: self.play_selected_clip())

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.LabelFrame(outer, text="Barra de hora", style="Card.TLabelframe", padding=14)
        bottom.pack(fill=X, pady=(12, 0))

        self.start_time_label = ttk.Label(bottom, text="Inicio: 00:00", style="Section.TLabel")
        self.start_time_label.pack(anchor="w")

        start_scale = ttk.Scale(bottom, from_=0, to=1439, variable=self.start_minutes_var, command=self._on_time_change)
        start_scale.pack(fill=X, pady=(6, 10))

        self.end_time_label = ttk.Label(bottom, text="Fin: 23:59", style="Section.TLabel")
        self.end_time_label.pack(anchor="w")

        end_scale = ttk.Scale(bottom, from_=0, to=1439, variable=self.end_minutes_var, command=self._on_time_change)
        end_scale.pack(fill=X, pady=(6, 0))

        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill=X, side="bottom")
        status_label = ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel", padding=(12, 8))
        status_label.pack(fill=X)

        self._update_channel_button_styles()

    def _build_connection_row(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill=X)

        fields = [
            ("IP DVR", self.ip_var, 18),
            ("Usuario", self.user_var, 12),
            ("Clave", self.password_var, 12),
        ]

        for label_text, variable, width in fields:
            cell = ttk.Frame(row, style="App.TFrame")
            cell.pack(side=LEFT, padx=(0, 12), fill=X)
            ttk.Label(cell, text=label_text, style="Muted.TLabel").pack(anchor="w")
            entry = ttk.Entry(cell, textvariable=variable, width=width, show="*" if label_text == "Clave" else "")
            entry.pack(anchor="w", fill=X, pady=(4, 0))

        date_cell = ttk.Frame(row, style="App.TFrame")
        date_cell.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(date_cell, text="Fecha", style="Muted.TLabel").pack(anchor="w")

        selector = ttk.Frame(date_cell, style="App.TFrame")
        selector.pack(anchor="w", pady=(4, 0))

        self.year_combo = ttk.Combobox(selector, width=8, textvariable=self.year_var, state="readonly")
        self.month_combo = ttk.Combobox(selector, width=5, textvariable=self.month_var, state="readonly")
        self.day_combo = ttk.Combobox(selector, width=5, textvariable=self.day_var, state="readonly")

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

    def _build_date_row(self, parent: ttk.Frame) -> None:
        helper = ttk.Frame(parent, style="App.TFrame")
        helper.pack(fill=X, pady=(12, 0))

        ttk.Label(helper, text="Rango temporal a consultar", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            helper,
            text="Ajusta la barra inferior para limitar la busqueda por hora dentro del dia seleccionado.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))

    def _channel_button_text(self, channel: int) -> str:
        return f"Canal {channel}\n{self.count_vars[channel].get()}"

    def _refresh_day_values(self) -> None:
        try:
            year = int(self.year_var.get())
            month = int(self.month_var.get())
        except ValueError:
            return

        try:
            if month == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month + 1, 1)
            last_day = (next_month - date.resolution).day
        except Exception:
            last_day = 31

        current_day = self.day_var.get()
        self.day_combo["values"] = [f"{day:02d}" for day in range(1, last_day + 1)]
        if current_day not in self.day_combo["values"]:
            self.day_var.set("01")

    def _sync_time_labels(self) -> None:
        start_text = self._minutes_to_text(int(float(self.start_minutes_var.get())))
        end_text = self._minutes_to_text(int(float(self.end_minutes_var.get())))
        self.start_time_label.configure(text=f"Inicio: {start_text}")
        self.end_time_label.configure(text=f"Fin: {end_text}")

    def _minutes_to_text(self, minute_value: int) -> str:
        minute_value = max(0, min(1439, int(minute_value)))
        hours, minutes = divmod(minute_value, 60)
        return f"{hours:02d}:{minutes:02d}"

    def _on_time_change(self, _value: str) -> None:
        start_minutes = int(float(self.start_minutes_var.get()))
        end_minutes = int(float(self.end_minutes_var.get()))

        if start_minutes > end_minutes:
            self.end_minutes_var.set(start_minutes)

        self._sync_time_labels()

    def _get_selected_date_iso(self) -> str:
        return f"{int(self.year_var.get()):04d}-{int(self.month_var.get()):02d}-{int(self.day_var.get()):02d}"

    def _get_time_range(self) -> tuple[str, str]:
        start_text = self._minutes_to_text(int(float(self.start_minutes_var.get())))
        end_text = self._minutes_to_text(int(float(self.end_minutes_var.get())))
        return start_text, end_text

    def start_search(self) -> None:
        if self._searching:
            return

        try:
            selected_date = self._get_selected_date_iso()
        except ValueError:
            messagebox.showerror("Fecha invalida", "Revisa la fecha seleccionada.")
            return

        start_time, end_time = self._get_time_range()
        if start_time > end_time:
            messagebox.showerror("Rango invalido", "La hora inicial no puede ser mayor que la final.")
            return

        self._set_searching(True)
        self.status_var.set(f"Buscando grabaciones del {selected_date}...")

        worker = threading.Thread(
            target=self._search_worker,
            args=(selected_date, start_time, end_time),
            daemon=True,
        )
        worker.start()

    def _set_searching(self, value: bool) -> None:
        self._searching = value
        state = "disabled" if value else "normal"
        self.search_button.configure(state=state)
        self.play_button.configure(state=state)
        self.clear_button.configure(state=state)

    def _search_worker(self, selected_date: str, start_time: str, end_time: str) -> None:
        clips: list[Clip] = []
        error_message = None

        try:
            for channel in DEFAULT_CHANNELS:
                clips.extend(self._fetch_clips(selected_date, channel, start_time, end_time))
        except Exception as exc:
            error_message = str(exc)

        def finish() -> None:
            if error_message:
                self.status_var.set("Error al buscar grabaciones.")
                messagebox.showerror("Busqueda fallida", error_message)
                self._all_clips = []
                self._render_results([])
            else:
                self._all_clips = sorted(clips, key=lambda item: (item.channel, item.start_dt))
                self._render_results(self._filtered_clips())
                self.status_var.set(f"Se encontraron {len(self._all_clips)} clips.")

            self._update_channel_counts()
            self._set_searching(False)

        self.root.after(0, finish)

    def _fetch_clips(self, selected_date: str, channel: int, start_time: str, end_time: str) -> list[Clip]:
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
            start_query = f"{selected_date}%20{start_time}"
            end_query = f"{selected_date}%20{end_time}"

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

    def _filtered_clips(self) -> list[Clip]:
        if self._selected_channel == 0:
            return list(self._all_clips)
        return [clip for clip in self._all_clips if clip.channel == self._selected_channel]

    def _render_results(self, clips: list[Clip]) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for clip in clips:
            self.tree.insert(
                "",
                "end",
                values=(
                    clip.channel,
                    clip.start,
                    clip.end,
                    clip.duration,
                    clip.file_size or "-",
                ),
            )

    def _update_channel_counts(self) -> None:
        for channel in DEFAULT_CHANNELS:
            count = sum(1 for clip in self._all_clips if clip.channel == channel)
            self.count_vars[channel].set(f"{count} clips")
            self.channel_buttons[channel].configure(text=self._channel_button_text(channel))

        self._update_channel_button_styles()

    def _update_channel_button_styles(self) -> None:
        for channel, button in self.channel_buttons.items():
            button.configure(style="ChannelSelected.TButton" if channel == self._selected_channel else "Channel.TButton")

    def select_channel(self, channel: int) -> None:
        if self._selected_channel == channel:
            self._selected_channel = 0
        else:
            self._selected_channel = channel

        self._update_channel_button_styles()
        self._render_results(self._filtered_clips())
        if self._selected_channel == 0:
            self.status_var.set(f"Mostrando todos los clips ({len(self._all_clips)}).")
        else:
            filtered = len(self._filtered_clips())
            self.status_var.set(f"Canal {self._selected_channel}: {filtered} clips.")

    def clear_filter(self) -> None:
        self._selected_channel = 0
        self._update_channel_button_styles()
        self._render_results(self._filtered_clips())
        self.status_var.set("Filtro limpiado.")

    def _selected_tree_clip(self) -> Clip | None:
        selection = self.tree.selection()
        if not selection:
            return None

        item = self.tree.item(selection[0])
        values = item.get("values", [])
        if len(values) < 4:
            return None

        channel = int(values[0])
        start = str(values[1])
        end = str(values[2])

        for clip in self._filtered_clips():
            if clip.channel == channel and clip.start == start and clip.end == end:
                return clip

        return None

    def play_selected_clip(self) -> None:
        clip = self._selected_tree_clip()
        if clip is None:
            messagebox.showinfo("Seleccion requerida", "Selecciona una grabacion antes de reproducirla.")
            return

        self.status_var.set(f"Reproduciendo canal {clip.channel}...")
        threading.Thread(target=self._play_clip, args=(clip,), daemon=True).start()

    def _play_clip(self, clip: Clip) -> None:
        ip_dvr = self.ip_var.get().strip()
        user = self.user_var.get().strip()
        password = self.password_var.get()

        start_query = clip.start.replace(" ", "%20")
        end_query = clip.end.replace(" ", "%20")
        url = (
            f"http://{user}:{password}@{ip_dvr}/cgi-bin/loadfile.cgi?action=startLoad"
            f"&channel={clip.channel}&startTime={start_query}&endTime={end_query}"
        )

        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            self.root.after(0, lambda: messagebox.showerror("Reproduccion fallida", "No se pudo abrir el clip seleccionado."))
            return

        window_name = f"Canal {clip.channel} - {clip.start}"
        while True:
            success, frame = capture.read()
            if not success:
                break

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(20) & 0xFF
            if key == ord("q"):
                break

        capture.release()
        cv2.destroyWindow(window_name)
        self.root.after(0, lambda: self.status_var.set(f"Clip finalizado: canal {clip.channel}."))


def main() -> None:
    root = Tk()
    DVRSearchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()