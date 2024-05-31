import logging
import os
import queue
from datetime import datetime
from pathlib import Path

from autotrainer.device import SerialInterface, HeadFixReader
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind
from autotrainer.video import TriggerManager

from tools.acquisition.model.user_settings import UserSettings
from tools.acquisition.model.video_capture_model import CAPTURE_TRIGGER_ID

logger = logging.getLogger(__name__)


class HeadFixModel:
    def __init__(self, user_settings: UserSettings):
        self._user_settings = user_settings

        self._msg_queue = queue.Queue()

        self._device_thread = None

        self._head_fix_reader = None

        self._is_connected = False

        self._load_trigger = self._user_settings.head_trigger

        self._is_triggered = False

        self._ports = list()

        self.refresh_ports()

    @property
    def head_fix_reader(self) -> HeadFixReader:
        return self._head_fix_reader

    @property
    def ports(self) -> list:
        return self._ports

    @property
    def port(self) -> str:
        return self._user_settings.head_port

    @port.setter
    def port(self, port: str):
        self._user_settings.head_port = port

    @property
    def load_trigger(self):
        return self._load_trigger

    @load_trigger.setter
    def load_trigger(self, value: int):
        self._load_trigger = value
        self._user_settings.head_trigger = value

    @property
    def is_connected(self):
        return self._is_connected

    def refresh_ports(self):
        self._ports = SerialInterface.refresh_ports()

    def update_position(self, value: int):
        if not self._is_connected:
            return
        self._device_thread.send_message(HeadFixMessageKind.SERVO, str(value))

    def tare(self):
        if not self._is_connected:
            return

        self._device_thread.send_message(HeadFixMessageKind.UPDATE_TARE)

    def connect_to_device(self):
        if len(self.port) == 0:
            return

        device_interface = SerialInterface(self.port)

        file_timestamp = datetime.now()
        location = os.path.join(self._user_settings.output_location, file_timestamp.strftime("%Y%m%d"),
                                self._user_settings.serial_number)
        path = Path(location)
        path.mkdir(parents=True, exist_ok=True)
        self._head_fix_reader.record_location = location

        head_fix = HeadFix(buffer_size=20)

        self._device_thread = DeviceThread(head_fix, device_interface, self._msg_queue)
        self._device_thread.name = "head-fix"

        self._device_thread.start()

        self._device_thread.send_message(DeviceThreadMessageKind.CONNECT)

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return

        if self._head_fix_reader is not None:
            self._head_fix_reader.record_location = None

        self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)

        self._is_connected = False

    def on_activated(self):
        self._head_fix_reader = HeadFixReader(self._msg_queue)
        self._head_fix_reader.start()

    def on_close(self):
        self.disconnect_from_device()
        # self._device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def monitor_trigger(self, values: list):
        # TODO debounce?
        for value in values:
            if not self._is_triggered:
                if value > self._load_trigger:
                    self._is_triggered = True
                    logger.info("trigger enabled")
                    TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)
            else:
                if value < self._load_trigger:
                    self._is_triggered = False
                    logger.info("trigger disabled")
                    TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)
