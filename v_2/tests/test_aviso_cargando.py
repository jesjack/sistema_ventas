"""AvisoTemporal (dialogs/aviso_cargando.py): el temporizador y el cierre, con un diálogo
falso -- no necesita una sesión de LibreOffice real (a diferencia del diálogo en sí, que sí la
necesita para dibujarse; eso se revisa a mano, ver NOTAS de camera_viewer sobre el harness de
Xvfb+soffice).

Correr desde v_2/: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_aviso_cargando -v"""

import time
import unittest
from unittest import mock

from dialogs import aviso_cargando
from dialogs.aviso_cargando import AvisoTemporal, mostrar_aviso_temporal


class DialogoFalso:
    def __init__(self) -> None:
        self.visible = None
        self.dispuesto = False

    def setVisible(self, visible) -> None:  # noqa: N802 (nombre de UNO)
        self.visible = visible

    def dispose(self) -> None:
        self.dispuesto = True


class AvisoTemporalTests(unittest.TestCase):
    def test_it_closes_itself_after_the_given_duration(self) -> None:
        dialogo = DialogoFalso()
        AvisoTemporal(dialogo, duracion_segundos=0.05)
        self.assertFalse(dialogo.dispuesto)  # recién creado: todavía no le tocó el temporizador
        time.sleep(0.2)
        self.assertFalse(dialogo.visible)
        self.assertTrue(dialogo.dispuesto)

    def test_closing_by_hand_cancels_the_automatic_timer(self) -> None:
        dialogo = DialogoFalso()
        aviso = AvisoTemporal(dialogo, duracion_segundos=10.0)
        aviso.cerrar()
        self.assertTrue(dialogo.dispuesto)
        aviso._temporizador.join(timeout=1.0)  # cancel() no es instantáneo: darle un momento a terminar
        self.assertFalse(aviso._temporizador.is_alive())

    def test_closing_twice_only_touches_the_dialog_once(self) -> None:
        dialogo = mock.Mock(spec=DialogoFalso())
        aviso = AvisoTemporal(dialogo, duracion_segundos=10.0)
        aviso.cerrar()
        aviso.cerrar()
        dialogo.dispose.assert_called_once()

    def test_a_disposed_or_already_closed_underlying_dialog_never_raises(self) -> None:
        dialogo = mock.Mock()
        dialogo.setVisible.side_effect = RuntimeError("la ventana de LibreOffice ya no existe")
        aviso = AvisoTemporal(dialogo, duracion_segundos=10.0)
        aviso.cerrar()  # no lanza

    def test_the_automatic_close_and_a_manual_close_racing_still_only_fire_once(self) -> None:
        dialogo = mock.Mock(spec=DialogoFalso())
        aviso = AvisoTemporal(dialogo, duracion_segundos=0.05)
        time.sleep(0.2)  # deja que el temporizador ya haya disparado
        aviso.cerrar()  # y además a mano
        dialogo.dispose.assert_called_once()


class MostrarAvisoTemporalTests(unittest.TestCase):
    def test_it_shows_the_dialog_right_away_and_returns_a_handle_to_close_it_early(self) -> None:
        dialogo = DialogoFalso()
        with mock.patch.object(aviso_cargando, "_crear_dialogo", return_value=dialogo) as crear:
            aviso = mostrar_aviso_temporal("ctx-uno-falso", "Abriendo cámaras…", titulo="Cámaras", duracion_segundos=10.0)
        crear.assert_called_once_with("ctx-uno-falso", "Cámaras", "Abriendo cámaras…")
        self.assertTrue(dialogo.visible)  # visible de inmediato, sin esperar al temporizador
        self.assertFalse(dialogo.dispuesto)
        aviso.cerrar()
        self.assertTrue(dialogo.dispuesto)

    def test_default_title_and_duration_are_reasonable(self) -> None:
        dialogo = DialogoFalso()
        with mock.patch.object(aviso_cargando, "_crear_dialogo", return_value=dialogo) as crear:
            aviso = mostrar_aviso_temporal("ctx-uno-falso", "Espere…")
        crear.assert_called_once_with("ctx-uno-falso", "Aviso", "Espere…")
        self.assertGreater(aviso._temporizador.interval, 0)
        aviso.cerrar()


if __name__ == "__main__":
    unittest.main()
