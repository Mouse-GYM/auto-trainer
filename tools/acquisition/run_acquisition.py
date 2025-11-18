import logging
import os
import signal
import sys

import verboselogs
from PySide6 import QtGui

from autotrainer.core.event import try_register_api_event_plugin
from autotrainer.core.logging import (get_verbose_logger, MULTIPROC_LOG_FORMAT, PreciseTimeFormatter, DateTimeFormats,
                                      get_log_queue_listener, thread_id_filter, get_console_handler, get_root_handler,
                                      get_log_queue_handler, repr_logger, repr_all_loggers)
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
    q_listener = get_log_queue_listener()
    if q_listener is not None:
        q_listener.add_file_handler(log_file)
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

    # top_logger = get_verbose_logger("autotrainer")
    # r_h = get_root_handler()
    # c_h = get_console_handler()
    # q_h = get_log_queue_handler()
    # logger.info("all loggers:\n%s", repr_all_loggers())
    # logger.info("top logger: %s", repr_logger(top_logger))
    # logger.info("console: level=%s", c_h.level)
    # logger.info("queue: level=%s", q_h.level)
    # logger.info("autotrainer: level=%s prop=%s handlers=%s",
    #             top_logger.level, top_logger.propagate, top_logger.handlers)


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

    window = MainWindow(app, preferences, configuration, "2.0.1", is_dev)

    # conveniently allow close/exit app with SIGINT (ctrl-c) :
    def handle_sigint(signum, frame):
        logger.notice("Got signal %s ; closing window..", signum)
        window.close()

    signal.signal(signal.SIGINT, handle_sigint)

    window.show()
    # window.showMaximized()
    window.move(QtGui.QGuiApplication.primaryScreen().availableGeometry().center() - window.rect().center())

    window.on_activated()

    app.aboutToQuit.connect(window.close)

    return app.exec()
