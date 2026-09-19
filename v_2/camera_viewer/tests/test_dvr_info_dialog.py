"""Regresión: cerrar la ventana de información MIENTRAS carga tumbaba todo el
proceso ("Bus error"), porque el hilo de trabajo era el último dueño de la
ventana y la destruía fuera del hilo de la interfaz. Se corren varios
procesos a la vez porque el fallo era una carrera (~45 % de las corridas).
Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_dvr_info_dialog"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = textwrap.dedent(
    """
    import sys, time
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from camera_viewer import dvr_info_dialog

    def fake_collect(host, fetcher, sampler, progress, stop, now_fn=None):
        for i in range(6):
            if stop.is_set():
                raise dvr_info_dialog.InfoCancelled()
            progress(i, 6, "paso")
            time.sleep(0.25)
        raise dvr_info_dialog.InfoCancelled()

    dvr_info_dialog.collect = fake_collect
    app = QApplication([])
    main = QWidget()
    main.show()

    def open_dialog():
        dialog = dvr_info_dialog.DvrInfoDialog("127.0.0.1", "u", "p", False, main)
        QTimer.singleShot(400, dialog.close)
        dialog.exec()

    QTimer.singleShot(100, open_dialog)
    QTimer.singleShot(2500, app.quit)
    sys.exit(app.exec())
    """
)


class CloseWhileLoadingTests(unittest.TestCase):
    def test_closing_the_dialog_while_it_loads_does_not_kill_the_process(self) -> None:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT)}
        processes = [
            subprocess.Popen([sys.executable, "-c", SCRIPT], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(8)
        ]
        codes = [process.wait(timeout=60) for process in processes]
        self.assertEqual(codes, [0] * 8)


if __name__ == "__main__":
    unittest.main()
