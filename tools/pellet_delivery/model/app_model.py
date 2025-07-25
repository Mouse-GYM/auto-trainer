import logging
import queue
import uuid
from pathlib import Path
from typing import Optional

from autotrainer.core import (ObservableObject, SystemMessageHandler, SystemCommandKind,
                              MessageHandler, Motor,
                              EventManager)
from autotrainer.core.logging import get_verbose_logger
from autotrainer.device import (CanDevice, CAN_IDENTIFIER, MotorConfigurationFile, PelletDelivery,
                                DeviceConnection, CompoundMovementFile)

from tools.pellet_delivery.model.user_settings import UserSettings

logger = get_verbose_logger(__name__)

# TODO: This is just to see if the behavior is correct.  They should end up somewhere that any application or script can
#  access.
_anshutz_travel_limits = {
    "x": (-10, 10),
    "y": (-10, 10),
    "z": (-10, 10),
}

_alogus_travel_limits = {
    "x": (0, 35),
    "y": (0, 35),
    "z": (0, 35),
}


class AppModel(ObservableObject):
    def __init__(self, allow_can_emulation: bool = False):
        super().__init__()

        self._allow_can_emulation = allow_can_emulation

        self._user_settings = UserSettings()

        self._hardware_configuration = None

        self._device_connection: Optional[DeviceConnection] = None

        self._message_handler = SystemMessageHandler(queue.Queue())
        self._message_handler.property_changed += self._message_handler_property_changed
        self._message_handler.ack_received += self.reader_ack_received

        self._is_connected = False

        self._firmware_version = ""

        # The values the device is reporting - not a requested value.
        self._x = None
        self._y = None
        self._z = None
        self._load_arm = None
        self._cover_arm = None

        self._front_door = None
        self._panel_door = None
        self._spare_door = None
        self._ext_button = None

        self._stimuli = None
        self._config = None

        self._command_pending = False
        self._last_command = None

        self._travel_limits = _anshutz_travel_limits

    @property
    def user_settings(self) -> UserSettings:
        return self._user_settings

    @property
    def allow_can_emulation(self) -> bool:
        return self._allow_can_emulation

    @property
    def hardware_configuration(self):
        return self._hardware_configuration

    @hardware_configuration.setter
    def hardware_configuration(self, value):
        self._hardware_configuration = self._on_property_changed("hardware_configuration", value,
                                                                 self._hardware_configuration)

    @property
    def is_connected(self):
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value):
        self._is_connected = self._on_property_changed("is_connected", value, self._is_connected)

    @property
    def firmware_version(self) -> str:
        return self._firmware_version

    @firmware_version.setter
    def firmware_version(self, value):
        if self._user_settings.port == CAN_IDENTIFIER:
            if value is None or value.find("Pellet") == -1:
                return
        self._firmware_version = self._on_property_changed("firmware_version", value,
                                                           self._firmware_version)

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = self._on_property_changed("x", value, self._x)

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        self._y = self._on_property_changed("y", value, self._y)

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, value):
        self._z = self._on_property_changed("z", value, self._z)

    @property
    def load_arm(self):
        return self._load_arm

    @load_arm.setter
    def load_arm(self, value):
        self._load_arm = self._on_property_changed("load_arm", value, self._load_arm)

    @property
    def cover_arm(self):
        return self._cover_arm

    @cover_arm.setter
    def cover_arm(self, value):
        self._cover_arm = self._on_property_changed("cover_arm", value, self._cover_arm)

    @property
    def travel_limits(self):
        return self._travel_limits

    @travel_limits.setter
    def travel_limits(self, value):
        self._travel_limits = self._on_property_changed("travel_limits", value, self._travel_limits)

    @property
    def command_pending(self):
        return self._command_pending

    @command_pending.setter
    def command_pending(self, value):
        self._command_pending = self._on_property_changed("command_pending", value,
                                                          self._command_pending)

    @property
    def front_door(self):
        return self._front_door

    @front_door.setter
    def front_door(self, value):
        self._front_door = self._on_property_changed(MessageHandler.FRONT_DOOR_PROPERTY, value,
                                                     self._front_door)

    @property
    def panel_door(self):
        return self._panel_door

    @panel_door.setter
    def panel_door(self, value):
        self._panel_door = self._on_property_changed(MessageHandler.DRAWER_DOOR_PROPERTY, value,
                                                     self._panel_door)

    @property
    def spare_door(self):
        return self._spare_door

    @spare_door.setter
    def spare_door(self, value):
        self._spare_door = self._on_property_changed(MessageHandler.SPARE_DOOR_PROPERTY, value,
                                                     self._spare_door)

    @property
    def ext_button(self):
        return self._ext_button

    @ext_button.setter
    def ext_button(self, value):
        self._ext_button = self._on_property_changed(MessageHandler.EXT_BUTTON_PROPERTY, value,
                                                     self._ext_button)

    @property
    def stimuli(self):
        return self._stimuli

    @stimuli.setter
    def stimuli(self, value):
        self._stimuli = self._on_property_changed(MessageHandler.STIMULI_PROPERTY, value,
                                                  self._stimuli)

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = self._on_property_changed("config", value, self._config)

    def send_home(self):
        self._send_command(SystemCommandKind.SEND_HOME, context=uuid.uuid4())

    def send_homing(self):
        self._send_command(SystemCommandKind.SEND_HOMING, context=uuid.uuid4())

    def load_pellet(self):
        self._send_command(SystemCommandKind.LOAD_PELLET, context=uuid.uuid4())

    def send_pellet(self):
        self._send_command(SystemCommandKind.SEND_PELLET, context=uuid.uuid4())

    def release_pellet(self):
        self._send_command(SystemCommandKind.RELEASE_PELLET, context=uuid.uuid4())

    def cover_pellet(self):
        self._send_command(SystemCommandKind.COVER_PELLET, context=uuid.uuid4())

    def set_x(self, value: int):
        self._send_command(SystemCommandKind.SET_X, value, context=uuid.uuid4())

    def set_y(self, value: int):
        self._send_command(SystemCommandKind.SET_Y, value, context=uuid.uuid4())

    def set_z(self, value: int):
        self._send_command(SystemCommandKind.SET_Z, value, context=uuid.uuid4())

    def move_x(self, value: int):
        self._send_command(SystemCommandKind.MOVE_X, value, context=uuid.uuid4())

    def move_y(self, value: int):
        self._send_command(SystemCommandKind.MOVE_Y, value, context=uuid.uuid4())

    def move_z(self, value: int):
        self._send_command(SystemCommandKind.MOVE_Z, value, context=uuid.uuid4())

    def set_config(self, config):
        self._send_command(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, config)

    def get_config(self, motor: Motor):
        self._send_command(SystemCommandKind.READ_MOTOR_CONFIGURATION, motor)

    def load_move_file(self, filename: str):
        if self._device_connection is not None:
            movements = CompoundMovementFile.from_file(filename)
            self._device_connection.use_compound_movements(movements)

    def connect_to_device(self):
        if len(self._user_settings.port) == 0:
            return

        if self._user_settings.port == CAN_IDENTIFIER:
            self._device_connection = DeviceConnection(CanDevice(),
                                                       self._message_handler.input_queue,
                                                       name="pellet-can")
            self.travel_limits = _alogus_travel_limits
        else:
            self._device_connection = DeviceConnection(PelletDelivery(self._user_settings.port),
                                                       self._message_handler.input_queue,
                                                       name="pellet_serial")
            self.travel_limits = _anshutz_travel_limits

        self._device_connection.request_connect()

        self._send_command(SystemCommandKind.REQUEST_VERSION)

        if self._hardware_configuration is None:
            for attempt in (
                MotorConfigurationFile.DEFAULT_LOCATION.expanduser(),
                Path.home().joinpath(".alogus_config.yaml"),
                Path.home().joinpath("alogus_config.yaml"),
            ):
                if attempt.exists():
                    logger.notice("Will load motor config %s", attempt)
                    self.hardware_configuration = attempt.as_posix()
                    break
            else:
                logger.warning("No motor config file found, motors are possibly unconfigured ; this might be critical")

        if self._hardware_configuration is not None:
            logger.info("Reading motor config file %s", self._hardware_configuration)
            try:
                motors_cfg = MotorConfigurationFile.from_file(self._hardware_configuration)
            except Exception as err:
                logger.error(
                    "failed to read motor configuration file %s: %s", self._hardware_configuration,
                    err)
                self.hardware_configuration = None
                raise  # do not take any risk
            else:
                self._device_connection.use_motor_configurations(motors_cfg)

        self._device_connection.load_default_move_config()

        self.is_connected = True

    def disconnect_from_device(self):
        if self._is_connected:
            # End DeviceConnection for this connection.  Do not kill the message handler which is connection agnostic.
            if self._device_connection is not None:
                self._device_connection.request_disconnect()
                self._device_connection = None

            self.is_connected = False

        self.firmware_version = ""

    def on_activated(self):
        self._message_handler.start()

    def on_close(self):
        self.disconnect_from_device()

        # End all threads so application exits cleanly.
        if self._device_connection is not None:
            self._device_connection.request_disconnect()
        if self._message_handler is not None:
            self._message_handler.request_terminate()

        EventManager.try_close_default()

    def _message_handler_property_changed(self, name: str, value, _old_value):
        if name == SystemMessageHandler.FIRMWARE_VERSION_PROPERTY:
            self.firmware_version = value
        elif name == MessageHandler.DEVICE_X_PROPERTY:
            self.x = value
        elif name == MessageHandler.DEVICE_Y_PROPERTY:
            self.y = value
        elif name == MessageHandler.DEVICE_Z_PROPERTY:
            self.z = value
        elif name == MessageHandler.LOAD_ARM_ANGLE_PROPERTY:
            self.load_arm = value
        elif name == MessageHandler.COVER_ARM_ANGLE_PROPERTY:
            self.cover_arm = value
        elif name == MessageHandler.FRONT_DOOR_PROPERTY:
            self.front_door = value
        elif name == MessageHandler.DRAWER_DOOR_PROPERTY:
            self.panel_door = value
        elif name == MessageHandler.SPARE_DOOR_PROPERTY:
            self.spare_door = value
        elif name == MessageHandler.EXT_BUTTON_PROPERTY:
            self.ext_button = value
        elif name == MessageHandler.STIMULI_PROPERTY:
            self.stimuli = value
        elif name == "config":
            self.config = value

    def reader_ack_received(self, ack):
        logger.info(f"ack context received: {ack}")
        if self._last_command is not None and ack == self._last_command:
            self._last_command = None
            self.command_pending = False

    def _send_command(self, message, data=None, *, context=None):
        if self._last_command is not None:
            logger.verbose("ignoring command %s while existing command is in process with context=%s",
                           self._last_command)
            return

        if context is not None:
            # If not planning to confirm the response token, don't block the UI.
            self.command_pending = True
            self._last_command = context

        # if context is not None:
        logger.debug("sending message %s with context: %s", message, context)
        if self._device_connection is not None:
            self._device_connection.send_message(message, data, context)
