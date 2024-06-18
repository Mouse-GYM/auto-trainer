import sys

from PySide6.QtWidgets import QApplication

from tools.pellet_delivery.model.app_model import AppModel
from tools.pellet_delivery.view.main_window import MainWindow


def run_pellet_delivery_ui():
    app = QApplication(sys.argv)

    model = AppModel()

    window = MainWindow(model)

    window.show()

    window.on_activated()

    return app.exec()
