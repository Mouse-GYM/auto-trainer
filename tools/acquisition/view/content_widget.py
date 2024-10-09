from PySide6.QtWidgets import QWidget


class ContentWidget(QWidget):
    def __init__(self):
        super().__init__()

    def set_is_editable(self, is_editable: bool):
        pass

    def set_is_capture_active(self, is_active: bool):
        pass

    def on_activated(self):
        pass

    def on_close(self):
        pass
