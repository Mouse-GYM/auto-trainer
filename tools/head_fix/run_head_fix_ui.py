import sys

from PySide6.QtWidgets import QApplication

from tools.head_fix.model.app_model import AppModel
from tools.head_fix.view.main_window import MainWindow


def run_head_fix_ui():
    app = QApplication(sys.argv)

    model = AppModel()

    window = MainWindow(model)

    window.show()

    window.on_activated()

    return app.exec()
