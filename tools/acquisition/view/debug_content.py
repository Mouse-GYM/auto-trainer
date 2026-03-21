from io import StringIO

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QCheckBox


class DebugView(QDialog):
    
    def __init__(self, main_window):
        super().__init__()
        self._main_window = main_window
        layout = QVBoxLayout()
        widget = self._use_exec_box = QCheckBox()
        widget.setText("Use exec instead of eval")
        layout.addWidget(widget)
        widget = self._cmd_line_edit = QLineEdit()
        widget.editingFinished.connect(self._on_cmd_changed)
        layout.addWidget(widget)
        label = self._output = QLabel()
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setLayout(layout)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        # self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._locals = {
            "w": main_window,
            "print": self._print,
        }


    def _print(self, *args, **kwargs):
        t = StringIO()
        print(*args, **kwargs, file=t)
        self._output.setText(t.getvalue())

    def _on_cmd_changed(self, use_exec=None):
        cmd = self._cmd_line_edit.text()
        if use_exec is None:
            use_exec = self._use_exec_box.isChecked()
        if cmd.startswith(("import ", "from ")):
            use_exec = True
        try:
            if use_exec:
                exec(cmd, self._locals)
                result = None
            else:
                try:
                    result = eval(cmd, self._locals)
                except SyntaxError:
                    self._on_cmd_changed(use_exec=True)
                    return
        except BaseException as err:
            result = err
        if result is not None:
            self._output.setText(str(result))
