import logging
import sys

from PySide6.QtWidgets import QApplication

from autotrainer.model import EnvironmentProvider
from tools.pellet_delivery.model.app_model import AppModel
from tools.pellet_delivery.view.main_window import MainWindow

logger = logging.getLogger(__name__)


def verify_log_location(log_location: str = "", device_name: str = ""):
    from pathlib import Path
    from datetime import datetime

    if not log_location:
        log_location = Path.home().joinpath("Documents").joinpath("RawDataLocal")
    else:
        log_location = Path(log_location)

    date_stamp = datetime.now().strftime("%Y%m%d")

    log_location = log_location.joinpath("pellet_ui")

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
        except (ValueError, TypeError):
            return None

    log_vals = [int(x) for x in log_files if int_map_fcn(x) is not None]

    if len(log_vals) == 0:
        idx = 1
    else:
        log_vals.sort(reverse=True)
        idx = log_vals[0] + 1

    file_handler = logging.FileHandler(f"{log_location}/{date_stamp}_{idx:03d}.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s\t [%(name)s] %(message)s"))
    logging.root.addHandler(file_handler)


def run_pellet_delivery_ui(allow_can_emulation: bool = False) -> int:
    verify_log_location()

    app = QApplication(sys.argv)

    EnvironmentProvider.enable_can_emulation(allow_can_emulation)

    model = AppModel()

    window = MainWindow(app, model)

    window.show()

    window.on_activated()

    return app.exec()
