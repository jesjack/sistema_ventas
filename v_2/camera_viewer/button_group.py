from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

BUTTON_GAP = 6  # hueco entre botones (y entre grupos de botones fundidos) de una fila

# Botones "fundidos" en uno solo (como un control segmentado): pegados, sin hueco entre ellos y
# sin esquinas redondeadas en los lados que se tocan; el borde compartido hace de divisoria.
# Solo se tocan radios y bordes: colores, hover y demás siguen viniendo de la hoja de estilo
# de la app (ver __main__.DARK_STYLESHEET).


def fuse_buttons(buttons: list[QPushButton], parent: QWidget | None = None) -> QWidget:
    """Un widget con `buttons` pegados en fila. Los botones conservan su señal y su estado."""
    container = QWidget(parent)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    last = len(buttons) - 1
    for index, button in enumerate(buttons):
        rules = []
        if index > 0:  # el borde izquierdo ya lo pone el derecho del anterior
            rules += ["border-top-left-radius: 0px", "border-bottom-left-radius: 0px", "border-left-width: 0px"]
        if index < last:
            rules += ["border-top-right-radius: 0px", "border-bottom-right-radius: 0px"]
        if rules:
            button.setStyleSheet(button.styleSheet() + " QPushButton { " + "; ".join(rules) + "; }")
        layout.addWidget(button)
    return container
