import logging
import queue
import uuid

from autotrainer.core.project import ProjectInfo
from autotrainer.device import SerialInterface, HeadFixReader
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind
from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID, ObservableObject

logger = logging.getLogger(__name__)


class HeadFixModel(ObservableObject):
    def __init__(self):
        super().__init__()

        self._port = None

        self._device_thread = None

        self._head_fix_reader = None

        self._reader_queue = queue.Queue()

        self._is_connected = False

        self._position = 0

        self._is_headbar_engaged = False

        self._load_trigger = 15

        self._is_load_cell_engaged = False

        self._is_force_detector_engaged = False

        self._output_location = ""

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
        return self._load_trigger

    @load_trigger.setter
    def load_trigger(self, value: int):
        self._load_trigger = self._on_property_changed("load_trigger", value, self._load_trigger)

    @property
    def output_location(self) -> str:
        return self._output_location

    @output_location.setter
    def output_location(self, value: str):
        self._output_location = self._on_property_changed("output_location", value, self._output_location)

    @property
    def is_headbar_engaged(self) -> bool:
        return self._is_headbar_engaged

    @property
    def is_load_cell_engaged(self) -> bool:
        return self._is_load_cell_engaged

    @property
    def is_force_detector_engaged(self) -> bool:
        return self._is_force_detector_engaged

    @property
    def position(self) -> int:
        return self._position

    def update_position(self, value: int):
        self._position = self._on_property_changed("position", value, self._position)

        return self._send_with_token(HeadFixMessageKind.SERVO, str(value))

    def tare(self):
        if not self._is_connected:
            return

        return self._send_with_token(HeadFixMessageKind.UPDATE_TARE)

    def connect_to_device(self, project_info: ProjectInfo):
        if not self.port or len(self.port) == 0:
            return

        device_interface = SerialInterface(self.port)

        self._head_fix_reader.project_info = project_info

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
        self._head_fix_reader = HeadFixReader(self._reader_queue)
        self._head_fix_reader.load_cell_monitor.threshold = self._load_trigger
        self._head_fix_reader.property_changed += self._header_fix_property_changed
        self._head_fix_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._reader_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def _header_fix_property_changed(self, name: str, value, _):
        if name == "is_headbar_engaged":
            self._is_headbar_engaged = self._on_property_changed("is_headbar_engaged", value,
                                                                 self._is_headbar_engaged)
        elif name == "is_load_cell_engaged":
            TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, value)
            self._is_load_cell_engaged = self._on_property_changed("is_load_cell_engaged", value,
                                                                   self._is_load_cell_engaged)
        if name == "is_force_detector_engaged":
            self._is_force_detector_engaged = self._on_property_changed("is_force_detector_engaged", value,
                                                                        self._is_force_detector_engaged)

    def load_configuration(self, conf):
        if "port" in conf:
            self.port = conf["port"]
        if "position" in conf:
            self.update_position(conf["position"])
        if "loadTrigger" in conf:
            self.load_trigger = conf["loadTrigger"]

    def write_configuration(self):
        return {"port": self.port, "position": self._position, "loadTrigger": self._load_trigger}

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
