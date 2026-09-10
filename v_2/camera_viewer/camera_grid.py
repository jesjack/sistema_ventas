from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QWidget

from .camera_panel import CameraPanel

DEFAULT_CHANNELS = (1, 2, 3, 4)


class CameraGrid(QWidget):
    """Grilla 2x2 de CameraPanel. Doble clic en un panel lo expande para
    que ocupe todo el espacio (spaneando las 2x2 celdas del layout) y
    oculta los otros 3; doble clic de nuevo regresa la grilla normal."""

    def __init__(self, channels: tuple[int, ...] = DEFAULT_CHANNELS, parent=None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        # Fijo a proposito (no dejar que QGridLayout las infiera): sin esto,
        # despues de que un panel expandido ocupa las 2x2 celdas y se
        # vuelve a repartir, el layout no recupera bien las proporciones y
        # dos paneles quedan angostos.
        self._layout.setColumnStretch(0, 1)
        self._layout.setColumnStretch(1, 1)
        self._layout.setRowStretch(0, 1)
        self._layout.setRowStretch(1, 1)

        self.panels: dict[int, CameraPanel] = {}
        self._expanded_channel: int | None = None

        for index, channel in enumerate(channels):
            panel = CameraPanel(channel, self)
            panel.double_clicked.connect(lambda ch=channel: self.toggle_expand(ch))
            self.panels[channel] = panel

        self._layout_as_grid()

    def toggle_expand(self, channel: int) -> None:
        if self._expanded_channel == channel:
            self._expanded_channel = None
            self._layout_as_grid()
        else:
            self._expanded_channel = channel
            self._layout_expanded(channel)

    def _layout_as_grid(self) -> None:
        for index, (channel, panel) in enumerate(self.panels.items()):
            panel.setVisible(True)
            self._layout.addWidget(panel, index // 2, index % 2, 1, 1)

    def _layout_expanded(self, channel: int) -> None:
        for other_channel, panel in self.panels.items():
            panel.setVisible(other_channel == channel)
        self._layout.addWidget(self.panels[channel], 0, 0, 2, 2)
