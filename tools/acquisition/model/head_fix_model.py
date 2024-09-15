import logging
import queue
import time
import uuid
from threading import Timer

import numpy

from autotrainer.core.project import ProjectInfo
from autotrainer.device import SerialInterface, HeadFixReader
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind
from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID, ObservableObject

from tools.acquisition.model.user_settings import UserSettings

logger = logging.getLogger(__name__)

TRIGGER_THRESHOLD_TIME = 0.5  # seconds
TRIGGER_MINIMUM_HOLD_TIME = 5.0  # seconds


class HeadFixModel(ObservableObject):
    def __init__(self, user_settings: UserSettings):
        super().__init__()
        # TODO Remove dependency
        self._settings = user_settings

        self._port = None

        self._device_thread = None

        self._head_fix_reader = None

        self._reader_queue = queue.Queue()

        self._is_connected = False

        self._position = 0

        self._load_trigger = 15

        self._output_location = ""

        self._is_triggered = False

        self._min_rec_time = 0
        self._last_trigger_start = 0
        self._trigger_was_high = False
        self._enable_trigger_debounce = Timer(1.0, lambda: None)
        self._disable_trigger_debounce = Timer(1.0, lambda: None)

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
        self._head_fix_reader = HeadFixReader(self._reader_queue, serial_number=self._settings.serial_number)
        self._head_fix_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        self._reader_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def monitor_trigger(self, values: list):
        self._trigger_response(numpy.mean(values))

    def _trigger_response(self, value):
        if value > self._load_trigger:
            self._disable_trigger_debounce.cancel()
            if not self._trigger_was_high:
                self._trigger_was_high = True
                self._enable_trigger_debounce = Timer(TRIGGER_THRESHOLD_TIME, self._trigger_enable)
                self._enable_trigger_debounce.start()
        else:
            self._enable_trigger_debounce.cancel()
            if self._trigger_was_high:
                self._trigger_was_high = False
                rec_time = time.perf_counter() - self._last_trigger_start
                self._disable_trigger_debounce = Timer(
                    1.0 if rec_time >= TRIGGER_MINIMUM_HOLD_TIME else TRIGGER_MINIMUM_HOLD_TIME - rec_time,
                    self._trigger_disable)
                self._disable_trigger_debounce.start()

    def _trigger_enable(self):
        if not self._is_triggered:
            self._is_triggered = True
            TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)
            self._last_trigger_start = time.perf_counter()

    def _trigger_disable(self):
        if self._is_triggered:
            self._is_triggered = False
            TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

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
