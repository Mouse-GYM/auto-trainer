import dataclasses
import logging
import math
from typing import Tuple, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QSpinBox, QWidget, QPushButton, QVBoxLayout, QHBoxLayout
from pyqtgraph import ViewBox

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import PerfMonitor, MessageHandler, SensorAnalysis, LoadCellMonitor, Offset3DTuple, \
    SystemMessageHandler
from autotrainer.pyside import PGWidget, HardwarePortComboBox, CardWidget, QtIndicator
from tools.acquisition.model.hardware_model import HardwareModel
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.user_preferences import UserPreferences

from tools.acquisition.view.content_widget import ContentWidget

logger = get_verbose_logger(__name__)


_ACTIVE_LOAD_CELL_COLOR = (0, 250, 154)
_INACTIVE_LOAD_CELL_COLOR = (240, 240, 240)


def _render_offset_3d_value(value: Optional[Offset3DTuple]) -> str:
    return "n/a" if value is None else ", ".join(f"{coord:.2f}" for coord in value)


@dataclasses.dataclass
class _GraphItem:
    index: int
    name: str
    display: str
    unit: str
    y_range: Tuple[int, int]


# NB: same order than SensorAnalysis.measurements_received method
AVAILABLE_GRAPHS = (
    _GraphItem(0, "weight", "Load cell weight", "gr", (-1, 101)),
    _GraphItem(1, "switch", "Switch", "On/Off", (-1, 2)),
    _GraphItem(2, "pressure", "Pressure", "Counts", (-1, 4099)),
    _GraphItem(3, "temperature", "Temperature", "\u00b0C", (-1, 40)),
    _GraphItem(4, "humidity", "Humidity", "%", (-1, 101)),
)


_graph_by_name = {
    graph.name: graph
    for graph in AVAILABLE_GRAPHS
}


class AnalysisContent(ContentWidget):
    diamond_triangle_offset_changed = Signal(str, name="diamond_triangle_offset_changed")
    star_triangle_offset_changed = Signal(str, name="star_triangle_offset_changed")
    measurement_graph_changed = Signal(str, name="measurement_graph_changed")

    def __init__(
        self,
        hardware_model: HardwareModel,
        inference_model: InferenceModel,
        analysis: SensorAnalysis,
        msg_handler: SystemMessageHandler,
        user_pref: UserPreferences,
    ):
        super().__init__()

        self._model = hardware_model
        self._analysis = analysis
        self._user_pref = user_pref

        # Header
        layout = QHBoxLayout()

        layout.addWidget(QLabel("D-T:"))
        self._triangle_diamond_offset = QLabel("n/a")
        self.diamond_triangle_offset_changed.connect(self._triangle_diamond_offset.setText)
        layout.addWidget(self._triangle_diamond_offset)

        layout.addWidget(QLabel("S-T:"))
        self._star_triangle_offset = QLabel("n/a")
        self.star_triangle_offset_changed.connect(self._star_triangle_offset.setText)
        layout.addWidget(self._star_triangle_offset)

        layout.addStretch(1)

        self._load_cell_monitor_engaged = QtIndicator(text="Load Cell")
        layout.addWidget(self._load_cell_monitor_engaged)

        self._headbar_pressure_monitor_engaged = QtIndicator(text="Headbar Pressure")
        layout.addWidget(self._headbar_pressure_monitor_engaged)

        self._headbar_switch_engaged = QtIndicator(text="Headbar DIO Switch")
        layout.addWidget(self._headbar_switch_engaged)

        self._card_widget = CardWidget(title="Analysis", header_right_layout=layout)

        content = QWidget(None)
        content.setLayout(QHBoxLayout())

        self._plot1 = PGWidget()
        self._plot1.setBackground("w")
        self._plot1.getPlotItem().getViewBox().setBackgroundColor(_INACTIVE_LOAD_CELL_COLOR)
        self._plot1.setMinimumHeight(140)
        self._plot1.scale_x = 100.0
        ticks = [0, 10, 25, 40, 50]
        self._plot1.getAxis("left").setTicks([[(tick, str(tick)) for tick in ticks]])
        self._plot1.getAxis("bottom").setLabel("Time (s)")

        self._selected_graph = None
        def on_measurement_graph_changed(graph_name: str):
            graph = _graph_by_name.get(graph_name, None)
            selected = self._selected_graph
            if graph is not None and (selected is None or graph.name != self._selected_graph.name):
                self._selected_graph = graph
                plot = self._plot1
                # plot.reset()  this makes the x axis value (time) to be reset too
                plot.replace_cache([])
                plot.update_plot([])  # force to nothing
                plot.getAxis("left").setLabel(f"{graph.display} {graph.unit}")
                plot.getViewBox().setRange(yRange=graph.y_range)
        on_measurement_graph_changed(
            _graph_by_name.get(user_pref.measurement_graph, AVAILABLE_GRAPHS[0]).name
        )
        self.measurement_graph_changed.connect(on_measurement_graph_changed)

        content.layout().addWidget(self._plot1)

        self._card_widget.setContentWidget(content)

        # Footer
        self._footer = QWidget(None)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Load Cell Threshold (g):"))
        self._load_cell = QLineEdit(None, None)
        self._load_cell.editingFinished.connect(self._update_trigger)
        self._load_cell.setText(str(self._analysis.load_cell_monitor.load_cell_engaged_threshold))
        layout.addWidget(self._load_cell)

        layout.addStretch(1)

        self._footer.setLayout(layout)

        self._card_widget.footer.setContent(self._footer)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._perf_monitor = PerfMonitor(name="headFixContent", units="mps", report_window=30)

        self.set_is_editable(False)

        self._model.property_changed += self._model_property_changed

        inference_model.star_triangle_offset_changed += self._star_triangle_offset_changed
        inference_model.diamond_triangle_offset_changed += self._diamond_triangle_offset_changed
        inference_model.triangle_pellet_offset_changed += self._triangle_pellet_offset_changed

        self._analysis.load_cell_monitor.property_changed += self._load_cell_monitor_property_changed

        msg_handler.measurement_callback = self._measurement_received
        user_pref.property_changed += self._on_user_pref_changed


    def set_is_capture_active(self, is_active: bool):
        if is_active:
            self._perf_monitor.reset()

    def use_cache(self):
        self._plot1.use_cache()
        self._load_cell_monitor_engaged.setState(self._analysis.load_cell_monitor.is_engaged)
        self._headbar_switch_engaged.setState(self._analysis.is_headbar_switch_engaged)
        self._headbar_pressure_monitor_engaged.setState(self._analysis.headbar_pressure_monitor.is_engaged)

    def _measurement_received(self, value):
        values = value[self._selected_graph.index]
        self._perf_monitor.add_cycles(len(values))
        self._plot1.cache_data(values)

    def _update_trigger(self):
        try:
            self._model.load_trigger = float(self._load_cell.text())
        except Exception as ex:
            logger.warning(ex)

    def _load_cell_monitor_property_changed(self, name, value, _):
        if name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            if value:
                self._plot1.getPlotItem().getViewBox().setBackgroundColor(_ACTIVE_LOAD_CELL_COLOR)
            else:
                self._plot1.getPlotItem().getViewBox().setBackgroundColor(_INACTIVE_LOAD_CELL_COLOR)
        elif name == LoadCellMonitor.LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY:
            self._load_cell.setText(str(value))

    def _model_property_changed(self, name, value, _):
        # If any of the values may be coming from a different thread (e.g., the device), a signal is generally needed
        # rather than direct set/update.
        if name == "load_trigger":  # not anymore used
            self._load_cell.setText(str(value))

    def _diamond_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        self.diamond_triangle_offset_changed.emit(_render_offset_3d_value(offset))

    def _star_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        self.star_triangle_offset_changed.emit(
            "n/a" if offset is None else f"{offset.distance:.2f} mm"
        )

    @staticmethod
    def _triangle_pellet_offset_changed(offset: Optional[Offset3DTuple]):
        # todo: do we display on UI ?
        if offset is None:
            return
        logger.spam("triangle pellet offset: %s distance=%.3f", offset, offset.distance)

    def _on_user_pref_changed(self, name: str, value, old_value):
        if name == UserPreferences.MEASUREMENT_GRAPH:
            self.measurement_graph_changed.emit(value)
