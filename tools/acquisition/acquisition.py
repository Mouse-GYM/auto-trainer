import logging
import sys
from multiprocessing import set_start_method

logging.basicConfig(level=logging.WARNING)
logging.getLogger('tools').setLevel(logging.DEBUG)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)


def main():
    from PySide6.QtWidgets import QApplication

    from tools.acquisition.model.app_model import AppModel
    from tools.acquisition.view.main_window import MainWindow

    app = QApplication(sys.argv)

    model = AppModel()

    window = MainWindow(model)

    window.show()

    window.on_activated()

    return app.exec()


if __name__ == '__main__':
    set_start_method("spawn")

    if main():
        sys.exit(0)
    else:
        sys.exit(1)
