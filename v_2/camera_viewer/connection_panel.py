from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget


class ConnectionPanel(QWidget):
    """Datos de conexion al DVR (IP, usuario, clave) -- vive junto al
    calendario, aprovechando el espacio que le sobra al hacerlo compacto.
    Incluye el boton que alterna entre ver grabaciones y ver en vivo."""

    live_toggle_clicked = Signal()

    def __init__(self, host: str, username: str, password: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.host_input = QLineEdit(host)
        self.user_input = QLineEdit(username)
        self.password_input = QLineEdit(password)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.setContentsMargins(4, 12, 4, 0)
        form.addRow("IP DVR", self.host_input)
        form.addRow("Usuario", self.user_input)
        form.addRow("Clave", self.password_input)

        self.live_toggle_button = QPushButton("Ver en vivo")
        self.live_toggle_button.clicked.connect(self.live_toggle_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self.live_toggle_button)

    def set_live_mode(self, is_live: bool) -> None:
        self.live_toggle_button.setText("Ver grabaciones" if is_live else "Ver en vivo")
