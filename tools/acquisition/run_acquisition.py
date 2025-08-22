import logging
import os
import sys

import verboselogs
from PySide6 import QtGui

from autotrainer.core.event import try_register_api_event_plugin
from autotrainer.core.logging import (get_verbose_logger, MULTIPROC_LOG_FORMAT, PreciseTimeFormatter, DateTimeFormats,
                                      get_queue_listener, thread_id_filter, get_console_handler, get_root_handler,
                                      get_queue_handler)
from autotrainer.pyside import CardHeader

logger = get_verbose_logger(__name__)

missing_file = "The configuration file {0} does not exist.  A default configuration will be loaded."

CardHeader.DEFAULT_BACKGROUND_COLOR = "#cfb87c"
CardHeader.DEFAULT_TITLE_COLOR = "black"


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
        except ValueError:
            # not an int
            return None

    log_vals = [int(x) for x in log_files if int_map_fcn(x) is not None]

    if len(log_vals) == 0:
        idx = 1
    else:
        log_vals.sort(reverse=True)
        idx = log_vals[0] + 1

    log_file = f"{log_location}/{date_stamp}_{device_name}_{idx:03d}.log"
    logger.verbose("Setting log file to %s", log_file)
    #
    q_listener = get_queue_listener()
    r_h = get_root_handler()
    c_h = get_console_handler()
    q_h = get_queue_handler()
    if q_listener is not None:
        # q_listener.handlers += (file_handler,)
        q_listener.add_file_handler(log_file)
        # if r_h == c_h:
        #     # root handler is console handler
        #     # queue handler goes to console as well
        #     logging.root.addHandler(file_handler)
        # else:
        #     pass
            # root handler is queue handler which already has console handler and we added file_handler to it
        # logger.info("q_listener.handlers=%s respect=%s",
        #             q_listener.handlers, q_listener.respect_handler_level)
    else:
        file_handler = logging.FileHandler(log_file)
        file_handler.addFilter(thread_id_filter)
        file_handler.setFormatter(
            PreciseTimeFormatter(
                MULTIPROC_LOG_FORMAT,
                datefmt=DateTimeFormats.year_precise,
                time_precision=6,
            )
        )
        file_handler.setLevel(verboselogs.SPAM + 1)  # writes everything up to DEBUG which reaches it
        logging.root.addHandler(file_handler)
    l = get_verbose_logger("autotrainer")
    logger.info("root logger: level=%s handlers=%s", logging.root.level, logging.root.handlers)
    logger.info("console: level=%s", c_h.level)
    # logger.info("file: level=%s", file_handler.level)
    logger.info("queue: level=%s", q_h.level)
    logger.info("autotrainer: level=%s prop=%s handlers=%s", l.level, l.propagate, l.handlers)


def run_acquisition(configuration: str = None, is_dev: bool = False, allow_can_emulation: bool = False) -> int:
    from PySide6.QtWidgets import QApplication

    from autotrainer.model import EnvironmentProvider

    from tools.acquisition.view.main_window import MainWindow
    from tools.acquisition.model.user_preferences import UserPreferences

    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    if not verify_configuration(configuration):
        return -1

    EnvironmentProvider.enable_can_emulation(allow_can_emulation)

    preferences = UserPreferences()

    get_console_handler().setLevel(preferences.log_level)
    logging.info("Set log level to %s", preferences.log_level)

    verify_log_location(preferences.log_location, preferences.serial_number)

    try_register_api_event_plugin()

    window = MainWindow(app, preferences, configuration, "2.0.0", is_dev)

    window.show()

    window.move(QtGui.QGuiApplication.primaryScreen().availableGeometry().center() - window.rect().center())

    window.on_activated()

    return app.exec()
