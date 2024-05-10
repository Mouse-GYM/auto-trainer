from PySide6.QtWidgets import QGridLayout, QLabel, QComboBox, QLineEdit, QPushButton, QCheckBox, QFileDialog, QWidget

from tools.acquisition.model.analysis_model import AnalysisModel


class AnalysisContent(QWidget):
    def __init__(self, model: AnalysisModel):
        super().__init__()

        self._model = model

        layout = QGridLayout()

        layout.setContentsMargins(10, 10, 10, 10)

        layout.setRowStretch(3, 1)

        layout.setColumnStretch(1, 1)

        layout.addWidget(QLabel("Analysis:"), 0, 0)

        combobox = QComboBox()
        combobox.addItem("None")
        combobox.addItem("Deferred")
        combobox.addItem("Real-time")

        # self.addWidget(combobox, 0, 1)

        self._is_enabled = QCheckBox("Enabled")
        self._is_enabled.setChecked(self._model.is_enabled)
        self._is_enabled.stateChanged.connect(self._is_enabled_state_changed)

        layout.addWidget(self._is_enabled, 0, 1)

        layout.addWidget(QLabel("Model:"), 1, 0)

        self._location = QLineEdit(self._model.model_location)
        self._location.editingFinished.connect(self._location_changed)
        layout.addWidget(self._location, 1, 1)

        self._browse_button = QPushButton("Select...")
        self._browse_button.clicked.connect(self._browse_for_location)
        layout.addWidget(self._browse_button, 1, 2)

        # layout.addWidget(QLabel("Algorithm:"), 2, 0)

        self._algorithm = QLineEdit(self._model.algorithm_location)
        self._algorithm.editingFinished.connect(self._algorithm_changed)
        # layout.addWidget(self._algorithm, 2, 1)

        self.setLayout(layout)

    def _is_enabled_state_changed(self, x: int):
        self._model.is_enabled = x != 0

    def _location_changed(self):
        self._model.model_location = self._location.text()

    def _algorithm_changed(self):
        self._model.algorithm_location = self._algorithm.text()

    def _browse_for_location(self):
        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", self._location.text())

        if len(dirname) > 0:
            self._location.setText(dirname)
            self._model.model_location = dirname
