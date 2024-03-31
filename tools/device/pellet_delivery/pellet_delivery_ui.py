import logging
import sys

from PySide6.QtWidgets import QApplication

from tools.device.pellet_delivery.model.app_model import AppModel
from tools.device.pellet_delivery.view.main_window import MainWindow

logging.basicConfig(level=logging.WARNING)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)


def main():
    app = QApplication(sys.argv)

    model = AppModel()

    window = MainWindow(model)

    window.show()

    window.on_activated()

    return app.exec()


if __name__ == '__main__':
    if main():
        sys.exit(0)
    else:
        sys.exit(1)