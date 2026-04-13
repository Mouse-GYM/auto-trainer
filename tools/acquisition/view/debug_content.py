import threading
from io import StringIO

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QCheckBox, QSizePolicy


class DebugView(QDialog):
    _sig_output_text_changed = Signal(str)
    _sig_append_output_text = Signal(str)
    _sig_enabled_changed = Signal(bool)
    
    def __init__(self, main_window):
        super().__init__()
        self.setWindowTitle("AutoTrainer Debug View")
        self._main_window = main_window
        layout = QVBoxLayout()
        widget = self._use_exec_box = QCheckBox()
        widget.setText("Use exec instead of eval")
        layout.addWidget(widget)
        self._cmd_line_edit = widget = QLineEdit()
        self._sig_enabled_changed.connect(widget.setEnabled)
        # only using returnPressed, a lot safer:
        widget.returnPressed.connect(self._on_cmd_return_pressed)
        layout.addWidget(widget)
        label = self._output_label = QLabel()
        label.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        self._sig_output_text_changed.connect(label.setText)
        self._sig_append_output_text.connect(self._append_text)
        label.setWordWrap(True)
        layout.addWidget(label)
        #
        self.setLayout(layout)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        # self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        # this is what can be used/referred to directly
        self._locals = {
            "w": main_window,
            "app": main_window.app_model,
            "print": self._print,
        }
        label.setText("You can use 'w' for main_window or 'app' for app_model in command ..")

    def _append_text(self, txt: str):
        prev = self._output_label.text()
        if not prev.endswith("\n"):
            prev += "\n"
        self._output_label.setText(prev + txt)

    def _print(self, *args, **kwargs):
        t = StringIO()
        print(*args, **kwargs, file=t)
        self._sig_append_output_text.emit(t.getvalue())

    def _execute_cmd(self, cmd, use_exec):
        try:
            if use_exec:
                exec(cmd, self._locals)
                result = None
            else:
                try:
                    result = eval(cmd, self._locals)
                except SyntaxError:
                    self._on_cmd_return_pressed(use_exec=True)
                    return
        except BaseException as err:
            result = err
        if result is not None:
            self._sig_append_output_text.emit(str(result))
        self._sig_enabled_changed.emit(True)

    def _on_cmd_return_pressed(self, use_exec=None):
        cmd = self._cmd_line_edit.text()
        if use_exec is None:
            use_exec = self._use_exec_box.isChecked()
        if cmd.startswith(("import ", "from ")):
            use_exec = True
        self._cmd_line_edit.setEnabled(False)
        self._output_label.setText(f"Executing {cmd}")
        th = threading.Thread(
            target=self._execute_cmd, daemon=True, name="debug-exec-cmd",
            args=(cmd, use_exec))
        th.start()
