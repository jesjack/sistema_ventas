from __future__ import annotations

from dataclasses import dataclass
import threading
from pathlib import Path


@dataclass(frozen=True)
class ButtonSpec:
    action_id: str
    label: str


class SheetButtonBridge:
    def __init__(self, uno_context, document, base_dir: Path, poll_interval: float = 0.5):
        self.uno_context = uno_context
        self.document = document
        self.base_dir = Path(base_dir)
        self.comm_dir = self.base_dir / "logs"
        self.event_file = self.comm_dir / "button_events.txt"
        self.poll_interval = max(0.1, float(poll_interval))
        self._buttons: list[ButtonSpec] = []
        self._handlers: dict[str, object] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_event_snapshot = ""
        self._script_provider = document.getScriptProvider()

    def add_button(self, label: str, handler) -> None:
        action_id = self._handler_to_action_id(handler)
        button = ButtonSpec(action_id, str(label))
        self._buttons.append(button)
        self._handlers[button.action_id] = handler

    def _handler_to_action_id(self, handler) -> str:
        handler_name = getattr(handler, "__name__", "")
        action_id = str(handler_name).strip().lower()
        if not action_id:
            raise ValueError("handler must have a function name")
        return action_id

    def activate(self, *, clear_events: bool = True) -> None:
        self.prepare(clear_events=clear_events)
        self.publish_layout()
        self.start()

    def prepare(self, *, clear_events: bool = True) -> None:
        self.comm_dir.mkdir(parents=True, exist_ok=True)
        self.event_file.touch(exist_ok=True)
        if clear_events:
            self.event_file.write_text("", encoding="utf-8")
            self._last_event_snapshot = ""

    def publish_layout(self) -> None:
        self._invoke_basic_macro("TPV_PrepararComunicacionMacro")
        self._invoke_basic_macro("TPV_LimpiarBotonesMacro")
        for button in self._buttons:
            self._invoke_basic_macro("TPV_CrearBotonMacro", button.action_id, button.label)

    def _invoke_basic_macro(self, macro_name: str, *args) -> None:
        macro_uri = f"vnd.sun.star.script:Standard.Module1.{macro_name}?language=Basic&location=document"
        script = self._script_provider.getScript(macro_uri)
        script.invoke(tuple(args), (), ())

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_events, name="SheetButtonBridge", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _watch_events(self) -> None:
        while not self._stop_event.wait(self.poll_interval):
            self._drain_events()

    def _drain_events(self) -> None:
        if not self.event_file.exists():
            return

        snapshot = self.event_file.read_text(encoding="utf-8")
        if snapshot == self._last_event_snapshot:
            return

        self._last_event_snapshot = snapshot

        for raw_line in snapshot.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) < 2:
                continue

            kind = parts[0].strip().upper()
            if kind != "CLICK":
                continue

            action_id = parts[1].strip()
            handler = self._handlers.get(action_id)
            if handler is None:
                print(f"[button_bridge] Click sin handler: {action_id}")
                continue

            try:
                handler()
            except Exception as exc:
                print(f"[button_bridge] Error al ejecutar {action_id}: {exc}")