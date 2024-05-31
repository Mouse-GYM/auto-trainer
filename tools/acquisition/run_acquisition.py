import sys


def run_acquisition():
    from PySide6.QtWidgets import QApplication

    from tools.acquisition.model.app_model import AppModel
    from tools.acquisition.view.main_window import MainWindow

    app = QApplication(sys.argv)

    model = AppModel()

    window = MainWindow(model)

    window.show()

    window.on_activated()

    return app.exec()
