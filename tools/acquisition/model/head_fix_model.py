import logging
import queue
import uuid
from typing import Optional

from autotrainer.core import ObservableObject, ProjectInfo
from autotrainer.device import SerialInterface, HeadFixReader
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind

logger = logging.getLogger(__name__)


class HeadFixModel(ObservableObject):
    def __init__(self):
        super().__init__()

        self._port = None

        self._device_thread = None

        self._reader_queue = queue.Queue()

        self._head_fix_reader = HeadFixReader(self._reader_queue)
        self._head_fix_reader.property_changed += self._head_fix_reader_property_changed

        self._is_connected = False

        self._position = 0

        self._is_headbar_engaged = False

        self._load_cell_threshold = 15

        self._is_load_cell_engaged = False

        self._is_force_detector_engaged = False

        self._output_location = ""

        self._head_fix_reader.load_cell_monitor.threshold = self._load_cell_threshold

        self._project: Optional[ProjectInfo] = None

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value

    @property
    def is_connected(self):
        return self._is_connected

    @property
    def head_fix_reader(self) -> HeadFixReader:
        return self._head_fix_reader

    @property
    def port(self) -> str:
        return self._port

    @port.setter
    def port(self, value: str):
        self._port = self._on_property_changed("port", value, self._port)

    @property
    def load_trigger(self):
        return self._load_cell_threshold

    @load_trigger.setter
    def load_trigger(self, value: int):
        self._load_cell_threshold = self._on_property_changed("load_trigger", value, self._load_cell_threshold)
        self._head_fix_reader.load_cell_monitor.threshold = self._load_cell_threshold

    @property
    def output_location(self) -> str:
        return self._output_location

    @output_location.setter
    def output_location(self, value: str):
        self._output_location = self._on_property_changed("output_location", value, self._output_location)

    @property
    def is_headbar_engaged(self) -> bool:
        return self._is_headbar_engaged

    @is_headbar_engaged.setter
    def is_headbar_engaged(self, value: bool):
        self._is_headbar_engaged = self._on_property_changed("is_headbar_engaged", value,
                                                             self._is_headbar_engaged)

    @property
    def is_load_cell_engaged(self) -> bool:
        return self._is_load_cell_engaged

    @is_load_cell_engaged.setter
    def is_load_cell_engaged(self, value: bool):
        self._is_load_cell_engaged = self._on_property_changed("is_load_cell_engaged", value,
                                                               self._is_load_cell_engaged)

    @property
    def is_force_detector_engaged(self) -> bool:
        return self._is_force_detector_engaged

    @is_force_detector_engaged.setter
    def is_force_detector_engaged(self, value: bool):
        self._is_force_detector_engaged = self._on_property_changed("is_force_detector_engaged", value,
                                                                    self._is_force_detector_engaged)

    @property
    def position(self) -> int:
        return self._position

    def update_position(self, value: int, set_baseline: bool = False):
        if set_baseline:
            self.property_changed("baseline_intensity", value, self._position)

        if value == self._position:
            return None

        self._position = self._on_property_changed("position", value, self._position)

        return self._send_with_token(HeadFixMessageKind.SERVO, str(value))

    def tare(self):
        if not self._is_connected:
            return

        return self._send_with_token(HeadFixMessageKind.UPDATE_TARE)

    def connect_to_device(self):
        if not self.port or len(self.port) == 0:
            return

        device_interface = SerialInterface(self.port)

        self._head_fix_reader.project_info = self._project

        head_fix = HeadFix(buffer_size=20)

        self._device_thread = DeviceThread(head_fix, device_interface, self._reader_queue)
        self._device_thread.name = "head-fix"

        self._device_thread.start()

        self._send_command(DeviceThreadMessageKind.CONNECT)

        self._send_command(HeadFixMessageKind.SERVO, str(self._position))

        self._send_command(HeadFixMessageKind.STREAM_START)

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return

        if self._head_fix_reader is not None:
            self._head_fix_reader.project_info = None

        self._send_command(DeviceThreadMessageKind.TERMINATE)

        self._device_thread = None

        self._is_connected = False

    def on_activated(self):
        self._head_fix_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._reader_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def _head_fix_reader_property_changed(self, name: str, value, _):
        if name == "is_headbar_engaged":
            self.is_headbar_engaged = value
        elif name == "is_load_cell_engaged":
            self.is_load_cell_engaged = value
        if name == "is_force_detector_engaged":
            self.is_force_detector_engaged = value

    def load_configuration(self, configuration: dict):
        if "port" in configuration:
            self.port = configuration["port"]
        if "position" in configuration:
            self.update_position(configuration["position"])
        if "loadTrigger" in configuration:
            logger.warning("the 'loadTrigger' property has been moved to a sub-property of the 'loadCell' property")
            self.load_trigger = configuration["loadTrigger"]
        if "loadCell" in configuration:
            load_cell_conf = configuration["loadCell"]
            if "loadTrigger" in load_cell_conf:
                self.load_trigger = load_cell_conf["loadTrigger"]
            if "minLoadOnDuration" in load_cell_conf:
                self._head_fix_reader.load_cell_monitor.threshold_duration = load_cell_conf["minLoadOnDuration"]
            if "minEventDuration" in load_cell_conf:
                self._head_fix_reader.load_cell_monitor.min_hold_duration = load_cell_conf["minEventDuration"]
            if "minLoadOffDuration" in load_cell_conf:
                self._head_fix_reader.load_cell_monitor.post_hold_duration = load_cell_conf["minLoadOffDuration"]
        if "autoTare" in configuration:
            auto_tare_conf = configuration["autoTare"]
            if "threshold" in auto_tare_conf:
                self._head_fix_reader.tare_detector.threshold = auto_tare_conf["threshold"]
            if "rangeThreshold" in auto_tare_conf:
                self._head_fix_reader.tare_detector.range_threshold = auto_tare_conf["rangeThreshold"]
            if "duration" in auto_tare_conf:
                self._head_fix_reader.tare_detector.duration = auto_tare_conf["duration"]

    def save_configuration(self) -> dict:
        load_cell = {"loadTrigger": self._head_fix_reader.load_cell_monitor.threshold,
                     "minLoadOnDuration": self._head_fix_reader.load_cell_monitor.threshold_duration,
                     "minEventDuration": self._head_fix_reader.load_cell_monitor.min_hold_duration,
                     "minLoadOffDuration": self._head_fix_reader.load_cell_monitor.post_hold_duration}

        auto_tare = {
            "threshold": self._head_fix_reader.tare_detector.threshold,
            "rangeThreshold": self._head_fix_reader.tare_detector.range_threshold,
            "duration": self._head_fix_reader.tare_detector.duration
        }

        return {"port": self.port, "position": self._position, "loadCell": load_cell, "autoTare": auto_tare}

    def _send_with_token(self, cmd, value=None):
        token = uuid.uuid4()

        if self._send_command(cmd, value, token):
            return token
        else:
            return None

    def _send_command(self, message, data=None, context=None) -> bool:
        if self._device_thread is not None:
            self._device_thread.send_message(message, data, context)
            return True

        return False
