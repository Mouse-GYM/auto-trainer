import logging
import os
import queue
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread

from autotrainer.serial_interface import SerialInterface
from autotrainer.head_fix import HeadFix, HeadFixMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind
from autotrainer.head_fix_measurement_reader import HeadFixMeasurementReader
from autotrainer.trigger_manager import TriggerManager

from tools.acquisition.model.user_settings import UserSettings
from tools.acquisition.model.video_capture_model import CAPTURE_TRIGGER_ID

logger = logging.getLogger(__name__)


class HeadFixModel:
    def __init__(self, user_settings: UserSettings):
        self._user_settings = user_settings

        self._cmd_queue = queue.Queue()
        self._msg_queue = queue.Queue()
        self._device_thread = None

        self._measurement_thread = QThread()
        self._measurement_worker = HeadFixMeasurementReader(self._msg_queue, self._user_settings.serial_number)
        self._measurement_worker.moveToThread(self._measurement_thread)
        self._measurement_thread.started.connect(self._measurement_worker.process)
        self._measurement_worker.weight_ready.connect(self._monitor_trigger)

        self._is_connected = False

        self._load_trigger = self._user_settings.head_trigger

        self._is_triggered = False

        self._ports = list()

        self.refresh_ports()

    @property
    def measurements(self) -> HeadFixMeasurementReader:
        return self._measurement_worker

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
        self._ports = SerialInterface.list_ports()

    def update_position(self, value: int):
        if not self._is_connected:
            return
        self._cmd_queue.put((HeadFixMessageKind.SERVO, str(value), None))

    def tare(self):
        if not self._is_connected:
            return

        self._cmd_queue.put((HeadFixMessageKind.UPDATE_TARE, None, None))

    def connect_to_device(self):
        if len(self.port) == 0:
            return

        with self._cmd_queue.mutex:
            self._cmd_queue.queue.clear()

        device_interface = SerialInterface(self.port)

        if self._measurement_worker is not None:
            file_timestamp = datetime.now()
            location = os.path.join(self._user_settings.output_location, file_timestamp.strftime("%Y%m%d"), self._user_settings.serial_number)
            path = Path(location)
            path.mkdir(parents=True, exist_ok=True)
            self._measurement_worker.record_location = location

        head_fix = HeadFix(device_interface, 100)

        self._device_thread = DeviceThread(head_fix, device_interface, self._cmd_queue, self._msg_queue)

        self._device_thread.start()

        self._measurement_thread.start()

        self._is_connected = True

    def disconnect_from_device(self):
        if not self._is_connected:
            return
        
        if self._measurement_worker is not None:
            self._measurement_worker.record_location = None

        self._cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None, None))

        self._is_connected = False

    def on_close(self):
        self.disconnect_from_device()
        self._cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None, None))
        self._msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))

    def _monitor_trigger(self, values: list):
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
