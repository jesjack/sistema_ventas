from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget

from . import progress_button
from .clip import Clip
from .export_clip import default_export_folder
from .export_hours import HoursExport, HoursSpec, plan, start_hours_export
from .hours_dialogs import HoursProgressDialog, HoursSelectDialog
from .hours_progress import HoursProgress
from .progress_button import ProgressButton

# Une el botón "Exportar" del panel izquierdo con la exportación de horas:
#   reposo  -> clic: ventana de selección (HoursSelectDialog) -> "Exportar" arranca el motor
#   corriendo/pausado/terminado -> el botón muestra el avance dentro de sí y un clic abre el panel de
#   avance (HoursProgressDialog); al cerrar el panel de una exportación ya terminada, vuelve al reposo.
# El motor (export_hours.py) corre en su hilo y solo pone avisos en una cola; aquí un temporizador
# los lee en el hilo de la interfaz.

SETTINGS_FOLDER_KEY = "export_hours_folder"
POLL_MS = 200
JOIN_TIMEOUT = 5.0


class HoursExportController(QObject):
    def __init__(
        self,
        button: ProgressButton,
        window: QWidget,
        clips_provider: Callable[[], dict[int, list[Clip]]],
        day_provider: Callable[[], date | None],
        credentials: Callable[[], tuple[str, str, str]],
        notify: Callable[[str], None],
        settings=None,
        now: Callable[[], datetime] = datetime.now,
        starter=start_hours_export,
        select_factory=HoursSelectDialog,
        progress_factory=HoursProgressDialog,
        confirm_cancel=None,
        open_folder: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(window)
        self.button, self._window = button, window
        self._clips_provider, self._day_provider, self._credentials = clips_provider, day_provider, credentials
        self._notify, self._settings, self._now = notify, settings, now
        self._starter, self._select_factory, self._progress_factory = starter, select_factory, progress_factory
        self._confirm_cancel = confirm_cancel
        self._open_folder = open_folder or (lambda folder: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
        self.export: HoursExport | None = None
        self.progress: HoursProgress | None = None
        self.panel: HoursProgressDialog | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        button.clicked.connect(self._on_button)
        self._show_idle()

    # -- estado -------------------------------------------------------------------------------------------

    def is_running(self) -> bool:
        return self.progress is not None and not self.progress.finished

    def is_active(self) -> bool:
        """Hay una exportación en curso o con su resultado aún sin ver."""
        return self.progress is not None

    # -- el botón -----------------------------------------------------------------------------------------

    def _on_button(self) -> None:
        if self.progress is None:
            self._select()
        else:
            self.show_panel()

    def _select(self) -> None:
        day, clips = self._day_provider(), self._clips_provider()
        if day is None:
            self._notify("Selecciona primero un día en el calendario.")
            return
        if not any(clips.values()):
            self._notify(f"No hay grabaciones del {day:%d/%m/%Y} para exportar.")
            return
        dialog = self._select_factory(day, clips, self._now(), self._load_folder(), self._window)
        if not dialog.exec():
            return
        self._save_folder(dialog.folder())
        self.start(dialog.spec())

    def _load_folder(self) -> Path:
        if self._settings is not None:
            saved = self._settings.value(SETTINGS_FOLDER_KEY)
            if saved:
                return Path(str(saved))
        return default_export_folder()

    def _save_folder(self, folder: Path) -> None:
        if self._settings is not None:
            self._settings.setValue(SETTINGS_FOLDER_KEY, str(folder))

    # -- arrancar / seguir --------------------------------------------------------------------------------

    def start(self, spec: HoursSpec) -> None:
        plans = plan(spec)
        if not plans:
            self._notify("No hay nada que exportar en las horas elegidas.")
            return
        host, user, password = self._credentials()
        self.progress = HoursProgress(spec, plans, parent=self)
        self.export = self._starter(host, user, password, spec)
        self._timer.start()
        self._update_button()
        self._notify(f"Exportando {len(plans)} canal{'es' if len(plans) != 1 else ''} en segundo plano; el botón «Exportar» muestra el avance.")

    def _poll(self) -> None:
        handle, progress = self.export, self.progress
        if handle is None or progress is None:
            self._timer.stop()
            return
        while True:
            try:
                event = handle.events.get_nowait()
            except Exception:
                break
            progress.apply(event)
        progress.changed.emit()
        self._update_button()
        if progress.finished:
            self._timer.stop()
            self._notify(self._summary(progress))

    @staticmethod
    def _summary(progress: HoursProgress) -> str:
        saved, total = progress.saved_count(), progress.total_count()
        if saved == total:
            return f"Exportación lista: {saved} archivo{'s' if saved != 1 else ''} en {progress.folder}."
        if progress.was_cancelled():
            return f"Exportación cancelada: se guardaron {saved} de {total} canales."
        return f"La exportación terminó con problemas: se guardaron {saved} de {total} canales."

    # -- el botón como barra de progreso ------------------------------------------------------------------

    def _update_button(self) -> None:
        progress = self.progress
        if progress is None:
            self._show_idle()
            return
        percent = int(progress.overall_fraction() * 100)
        tip = "Clic para ver el avance"
        if progress.finished:
            saved, total = progress.saved_count(), progress.total_count()
            if saved == total:
                self.button.set_state(progress_button.DONE, "Exportación lista", 1.0, "Clic para ver el resultado")
            elif saved == 0:
                self.button.set_state(progress_button.ERROR, "Exportación fallida" if not progress.was_cancelled() else "Exportación cancelada", 1.0, "Clic para ver el resultado")
            else:
                self.button.set_state(progress_button.ERROR, f"Exportación parcial ({saved}/{total})", 1.0, "Clic para ver el resultado")
        elif progress.paused:
            self.button.set_state(progress_button.PAUSED, f"Pausado · {percent} %", progress.overall_fraction(), "En pausa mientras hay una vista en vivo. " + tip)
        elif progress.cancelling:
            self.button.set_state(progress_button.RUNNING, "Cancelando…", progress.overall_fraction(), tip)
        else:
            self.button.set_state(progress_button.RUNNING, f"Exportando… {percent} %", progress.overall_fraction(), tip)

    def _show_idle(self) -> None:
        self.button.set_state(progress_button.IDLE, None, 0.0, "Exportar horas o el día completo de uno o varios canales")

    # -- el panel -----------------------------------------------------------------------------------------

    def show_panel(self) -> None:
        progress = self.progress
        if progress is None:
            return
        if self.panel is None:
            panel = self._progress_factory(progress, self._window, self._confirm_cancel)
            panel.cancel_requested.connect(self.cancel)
            panel.open_folder_requested.connect(lambda: self._open_folder(progress.folder))
            panel.dismissed.connect(self._dismissed)
            self.panel = panel
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def cancel(self) -> None:
        if self.export is not None:
            self.export.cancel()
        if self.progress is not None:
            self.progress.request_cancel()
            self._update_button()

    def _dismissed(self) -> None:
        """Se cerró el panel de una exportación ya terminada: el botón vuelve a "Exportar"."""
        self.panel = None
        self.export = None
        self.progress = None
        self._show_idle()

    def shutdown(self) -> None:
        """Al cerrar la app: cancela y deja que el hilo borre sus archivos temporales."""
        if self.export is not None and not self.export.finished():
            self.export.cancel()
            if self.export.thread is not None:
                self.export.thread.join(timeout=JOIN_TIMEOUT)
        self._timer.stop()
