from PySide6.QtGui import Qt
from PySide6.QtWidgets import QWidget, QFormLayout, QSlider, QLabel, QHBoxLayout

from autotrainer.behavior import BehaviorModelProperties


class BehaviorModelPropertyWidget(QWidget):
    def __init__(self, model: BehaviorModelProperties):
        super().__init__()

        self.model = model

        layout = QFormLayout()

        self._baseline_intensity_slider = QSlider(Qt.Horizontal)
        self._baseline_intensity_slider.setMinimum(model.limits.min_baseline_intensity)
        self._baseline_intensity_slider.setMaximum(model.limits.max_baseline_intensity)
        self._baseline_intensity_slider.valueChanged.connect(self._baseline_intensity_changed)

        self._baseline_intensity_label = QLabel(f"{self.model.baseline_intensity}%")

        h_layout = QHBoxLayout()
        h_layout.addWidget(self._baseline_intensity_slider)
        h_layout.addWidget(self._baseline_intensity_label)

        layout.addRow("Baseline Intensity:", h_layout)

        self.setLayout(layout)

    def _baseline_intensity_changed(self, value: int):
        self.model.baseline_intensity = round(value)
        self._baseline_intensity_label.setText(f"{self.model.baseline_intensity}%")
