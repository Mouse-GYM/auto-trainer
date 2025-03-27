import logging
import os
import sys

from PySide6 import QtGui

logger = logging.getLogger(__name__)

missing_file = "The configuration file {0} does not exist.  A default configuration will be loaded."


def verify_configuration(configuration: str):
    from PySide6.QtWidgets import QMessageBox

    if configuration and not os.path.exists(configuration):
        # noinspection PyTypeChecker
        result = QMessageBox.warning(None, "Configuration File not Found", missing_file.format(configuration),
                                     QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Close)
        return result == QMessageBox.StandardButton.Ok

    return True


def verify_log_location(log_location: str, device_name: str):
    from pathlib import Path
    from datetime import datetime

    if not log_location:
        log_location = Path.home().joinpath("Documents").joinpath("RawDataLocal")
    else:
        log_location = Path(log_location)

    if not device_name:
        device_name = "AutoTrainer"

    date_stamp = datetime.now().strftime("%Y%m%d")

    log_location = log_location.joinpath(date_stamp).joinpath(device_name)

    if not log_location.exists():
        try:
            log_location.mkdir(parents=True)
        except Exception as e:
            logger.error(f"Failed to create log location {log_location}: {e}")
            return

    log_files = [x.name[-6:-4] for x in log_location.iterdir() if x.is_file() and device_name in x.name]

    def int_map_fcn(value: str):
        try:
            return int(value)
        except:
            return None

    log_vals = [int(x) for x in log_files if int_map_fcn(x) is not None]

    if len(log_vals) == 0:
        idx = 1
    else:
        log_vals.sort(reverse=True)
        idx = log_vals[0] + 1

    file_handler = logging.FileHandler(f"{log_location}/{date_stamp}_{device_name}_{idx:03d}.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s\t [%(name)s] %(message)s"))
    logging.root.addHandler(file_handler)


def run_acquisition(configuration: str = None, is_dev: bool = False):
    from PySide6.QtWidgets import QApplication

    from tools.acquisition.view.main_window import MainWindow
    from tools.acquisition.model.user_preferences import UserPreferences

    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    if not verify_configuration(configuration):
        return -1

    preferences = UserPreferences()

    verify_log_location(preferences.log_location, preferences.serial_number)

    window = MainWindow(app, preferences, configuration, "1.1.34", is_dev)

    window.show()

    window.move(QtGui.QGuiApplication.primaryScreen().availableGeometry().center() - window.rect().center())

    window.on_activated()

    return app.exec()
