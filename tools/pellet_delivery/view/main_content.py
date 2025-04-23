import logging

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPlainTextEdit, QVBoxLayout
from tools.pellet_delivery.model.app_model import AppModel
from tools.pellet_delivery.view.pellet_control import PelletControl
from tools.pellet_delivery.view.pellet_status import PelletStatus
from tools.pellet_delivery.view.pellet_state import PelletState
from tools.view.basic_panel import create_panel
from tools.view.connection_panel import ConnectionPanel

from autotrainer.pyside import TextBoxHandler


def create_log_panel():
    layout = QHBoxLayout()

    log_output = QPlainTextEdit()
    log_output.setReadOnly(True)
    log_output.setStyleSheet("border: none")
    layout.addWidget(log_output)

    return log_output, create_panel("Logs", layout)


class MainContent(QWidget):

    def __init__(self, app_view_model: AppModel):
        super().__init__()

        self._app_view_model = app_view_model
        self._app_view_model.property_changed += self._model_property_changed

        self._is_diagnostics_visible = True

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setStretch(3, 1)

        self._connection_panel = ConnectionPanel(app_view_model, "Pellet")
        self._connection_panel.connecting.connect(lambda: self._pellet_control.setEnabled(True))
        self._connection_panel.disconnected.connect(lambda: self._pellet_control.setEnabled(False))
        layout.addWidget(self._connection_panel)

        self._pellet_control = PelletControl(self._app_view_model)
        layout.addWidget(self._pellet_control)

        self._pellet_status = PelletStatus(self._app_view_model)
        layout.addWidget(self._pellet_status)

        self._pellet_state = PelletState(self._app_view_model)
        layout.addWidget(self._pellet_state)

        log_output, self._diagnostics_panel = create_log_panel()
        layout.addWidget(self._diagnostics_panel)

        handler = TextBoxHandler(log_output)
        handler.setFormatter(
            logging.Formatter(fmt="%(asctime)s: %(levelname)s: %(name)s: %(message)s"))
        logging.getLogger("autotrainer").addHandler(handler)

        self._layout = layout
        self.setLayout(self._layout)

    @property
    def is_diagnostics_visible(self) -> bool:
        return self._is_diagnostics_visible

    def on_activated(self):
        pass

    def set_diagnostics_visible(self, is_visible: bool):
        self._diagnostics_panel.setVisible(is_visible)
        self._is_diagnostics_visible = is_visible

        if is_visible:
            self._layout.setStretch(3, 1)
            self._layout.setStretch(2, 0)
        else:
            self._layout.setStretch(3, 0)
            self._layout.setStretch(2, 1)

    def on_connection(self, method):
        self._connection_panel.connecting.connect(method)

    def on_disconnect(self, method):
        self._connection_panel.disconnected.connect(method)

    def _model_property_changed(self, name: str, value: object, _: object):
        if name == "command_pending":
            self._pellet_control.setEnabled((not value) and self._app_view_model.is_connected)
