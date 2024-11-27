import os
import sys

from PySide6 import QtGui

missing_file = "The configuration file {0} does not exist.  A default configuration will be loaded."


def verify_configuration(configuration: str):
    from PySide6.QtWidgets import QMessageBox

    if configuration and not os.path.exists(configuration):
        # noinspection PyTypeChecker
        result = QMessageBox.warning(None, "Configuration File not Found", missing_file.format(configuration),
                                     QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Close)
        return result == QMessageBox.StandardButton.Ok

    return True


def run_acquisition(configuration: str = None):
    from PySide6.QtWidgets import QApplication

    from tools.acquisition.view.main_window import MainWindow

    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    if not verify_configuration(configuration):
        return -1

    window = MainWindow(app, configuration, "1.1.17")

    window.show()

    window.move(QtGui.QGuiApplication.primaryScreen().availableGeometry().center() - window.rect().center())

    window.on_activated()

    return app.exec()
