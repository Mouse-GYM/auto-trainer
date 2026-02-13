import logging
import os
import signal
import sys

from PySide6 import QtGui

from autotrainer.core import EventManager, ApiEventKind
from autotrainer.core.event import try_register_api_event_plugin
from autotrainer.core.logging import (get_verbose_logger, get_console_handler, set_log_location)
from autotrainer.pyside import CardHeader

from autotrainer.behavior import BehaviorAlgorithm

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
    device = "unnamed" if not preferences.serial_number else preferences.serial_number
    set_log_location(device)

    logging.info("Set log level to %s", preferences.log_level)
    get_console_handler().setLevel(preferences.log_level)

    event_manager = EventManager.default()
    plugin = try_register_api_event_plugin()

    window = MainWindow(app, preferences, configuration, is_dev)
    if plugin is not None:
        window.app_model.rpc_service = plugin.service

    # conveniently allow close/exit app with SIGINT (ctrl-c) :
    sigint_received = 0
    def handle_sigint(signum, frame):
        nonlocal sigint_received
        sigint_received += 1
        logger.notice("Got signal %s ; closing window..", signum)
        window.close()
        if sigint_received > 2:
            logger.critical("too many sigint, exiting with SIG_TERMINATE ..")
            os.kill(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGINT, handle_sigint)

    window.show()
    # window.showMaximized()
    window.move(QtGui.QGuiApplication.primaryScreen().availableGeometry().center() - window.rect().center())

    window.on_activated()

    EventManager.default().post_event_content(ApiEventKind.applicationLaunched)

    logger.info("Executing app now ..")
    try:
        return app.exec()
    finally:
        logger.verbose("Closing event manager and behavior algo thread handler..")
        event_manager.post_event_content(ApiEventKind.applicationTerminating)
        event_manager.close()
        BehaviorAlgorithm.close_algorithm_handler()
