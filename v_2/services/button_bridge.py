from __future__ import annotations

from dataclasses import dataclass
import os
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
        # Carpeta de "spool": la macro Basic (TPV_EscribirEvento) escribe un
        # archivo NUEVO por cada clic en vez de sobreescribir uno compartido.
        # Antes, un unico button_events.txt causaba "Error de E/S del
        # dispositivo" en Basic cuando este hilo lo leia justo cuando Basic
        # intentaba escribirlo -- con un archivo por evento esa carrera no
        # puede ocurrir (nunca hay dos procesos tocando el mismo archivo).
        self.events_dir = self.base_dir / "share" / "logs" / "events"
        self.poll_interval = max(0.1, float(poll_interval))
        self._buttons: list[ButtonSpec] = []
        self._handlers: dict[str, object] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
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
        self.events_dir.mkdir(parents=True, exist_ok=True)
        if clear_events:
            self._clear_pending_events()
        self._relax_permissions()

    def _clear_pending_events(self) -> None:
        for stale in self.events_dir.glob("*"):
            try:
                stale.unlink()
            except OSError:
                pass

    def _relax_permissions(self) -> None:
        # main.py se lanza con sudo en produccion (Linux), asi que este
        # proceso corre como root. Si el directorio queda con el umask por
        # defecto de root, el usuario normal (que es quien corre la macro
        # Basic dentro de soffice) no podria crear ahi el siguiente evento.
        # No aplica en Windows.
        if os.name == "nt":
            return
        for target in (self.events_dir.parent, self.events_dir):
            try:
                os.chmod(target, 0o777)
            except OSError:
                pass

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
            try:
                self._drain_events()
            except OSError as exc:
                # No deberia pasar con el esquema de spool (cada archivo es
                # inmutable una vez que aparece como .evt), pero por si algo
                # externo al diseno interfiere (antivirus, etc.), no dejamos
                # que esto mate el hilo -- se reintenta en el siguiente poll.
                print(f"[button_bridge] Error leyendo eventos (se reintenta en {self.poll_interval}s): {exc}")

    def _drain_events(self) -> None:
        if not self.events_dir.exists():
            return

        for event_path in sorted(self.events_dir.glob("*.evt")):
            try:
                line = event_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                print(f"[button_bridge] No se pudo leer {event_path.name}, se reintenta despues: {exc}")
                continue

            try:
                event_path.unlink()
            except OSError:
                pass

            self._handle_event_line(line)

    def _handle_event_line(self, line: str) -> None:
        if not line:
            return

        parts = line.split("|")
        if len(parts) < 2:
            return

        kind = parts[0].strip().upper()
        if kind != "CLICK":
            return

        action_id = parts[1].strip()
        handler = self._handlers.get(action_id)
        if handler is None:
            print(f"[button_bridge] Click sin handler: {action_id}")
            return

        try:
            handler()
        except Exception as exc:
            print(f"[button_bridge] Error al ejecutar {action_id}: {exc}")
