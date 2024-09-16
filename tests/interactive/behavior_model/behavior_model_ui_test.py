import logging
import sys

from PySide6.QtWidgets import QApplication

from tests.interactive.behavior_model.behavior_model_window import BehaviorModelWindow

logging.basicConfig(level=logging.WARNING)
logging.getLogger("tools").setLevel(logging.DEBUG)
logging.getLogger("autotrainer").setLevel(logging.DEBUG)


def main():
    app = QApplication(sys.argv)

    window = BehaviorModelWindow()

    window.show()

    return app.exec()


if __name__ == '__main__':
    main()
