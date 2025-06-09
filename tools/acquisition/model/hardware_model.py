import logging
from queue import Queue
from uuid import UUID, uuid4
from typing import Optional

from autotrainer.core import ObservableObject, SystemCommandKind, MessageHandler, AnimalSubject
from autotrainer.behavior import TunnelDeviceProtocol, PelletDeviceProtocol
from autotrainer.device import (DeviceConnectionProtocol, CAN_IDENTIFIER, HAVE_CAN_DEVICE, DeviceConnection, CanDevice,
                                HeadFix, PelletDelivery)

logger = logging.getLogger(__name__)


class HardwareModel(ObservableObject, TunnelDeviceProtocol, PelletDeviceProtocol):
    TUNNEL_VERSION_PROPERTY = "tunnel_version"
    PELLET_VERSION_PROPERTY = "pellet_version"

    TUNNEL_IDENTIFIER_PROPERTY = "tunnel_identifier"
    PELLET_IDENTIFIER_PROPERTY = "pellet_identifier"

    def __init__(self, message_handler: MessageHandler):
        super().__init__()

        self._tunnel_identifier: Optional[str] = None
        self._pellet_identifier: Optional[str] = None

        self._tunnel_device: Optional[DeviceConnectionProtocol] = None
        self._pellet_device: Optional[DeviceConnectionProtocol] = None

        message_handler.property_changed += self._message_handler_property_changed

        self._head_magnet_position: Optional[float] = None

        # Support for relative x, y, z movements and whether they are persistent as the Send position various between
        # hardware implementations.  One the Alogus hardware is used exclusively, it should be possible to remove these
        # and rely on SET_X/Y/Z commands with the extra arguments that support relative and/or movements that should
        # not affect the Send position.
        self._last_x: Optional[int] = None
        self._last_y: Optional[int] = None
        self._last_z: Optional[int] = None

    @property
    def tunnel_identifier(self) -> Optional[str]:
        return self._tunnel_identifier

    @tunnel_identifier.setter
    def tunnel_identifier(self, value: str):
        self._tunnel_identifier = self._on_property_changed(HardwareModel.TUNNEL_IDENTIFIER_PROPERTY, value,
            self._tunnel_identifier)

    @property
    def pellet_identifier(self) -> Optional[str]:
        return self._pellet_identifier

    @pellet_identifier.setter
    def pellet_identifier(self, value: str):
        self._pellet_identifier = self._on_property_changed(HardwareModel.PELLET_IDENTIFIER_PROPERTY, value,
            self._pellet_identifier)

    @property
    def head_magnet_intensity(self) -> Optional[float]:
        """
        This value is stored because there are other operations that depend on the current magnet intensity.  In most
        other cases, the only action is to update the UI with the current value.
        :return intensity in percent:
        """
        return self._head_magnet_position

    def update_head_magnet_intensity(self, value: float) -> Optional[UUID]:
        if isinstance(value, str):
            value = float(value)

        return self._send_with_token(self._tunnel_device, SystemCommandKind.MOVE_MAGNET_SERVO,
                                     value)

    def open_tunnel_gate(self) -> Optional[UUID]:
        return self._send_with_token(self._tunnel_device, SystemCommandKind.OPEN_TUNNEL_GATE)

    def close_tunnel_gate(self) -> Optional[UUID]:
        return self._send_with_token(self._tunnel_device, SystemCommandKind.CLOSE_TUNNEL_GATE)

    def tare_load_cell(self) -> Optional[UUID]:
        return self._send_with_token(self._tunnel_device, SystemCommandKind.UPDATE_SCALE_TARE)

    def set_x(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.SET_X, value)

    def set_y(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.SET_Y, value)

    def set_z(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.SET_Z, value)

    def move_x(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        if not absolute:
            if self._last_x is None:
                logger.warning("relative x movement requested, but no last x position is set")
                return None
            value += self._last_x
        return self._send_with_token(self._pellet_device, SystemCommandKind.MOVE_X, value)

    def move_y(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        if not absolute:
            if self._last_y is None:
                logger.warning("relative y movement requested, but no last y position is set")
                return None
            value += self._last_y
        return self._send_with_token(self._pellet_device, SystemCommandKind.MOVE_Y, value)

    def move_z(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        if not absolute:
            if self._last_z is None:
                logger.warning("relative z movement requested, but no last z position is set")
                return None
            value += self._last_z
        return self._send_with_token(self._pellet_device, SystemCommandKind.MOVE_Z, value)

    def send_home(self) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.SEND_HOME)

    def load_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.LOAD_PELLET)

    def send_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.SEND_PELLET)

    def release_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.RELEASE_PELLET)

    def cover_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.COVER_PELLET)

    def play_tone(self, frequency: int, _duration: float) -> Optional[UUID]:
        return self._send_with_token(self._pellet_device, SystemCommandKind.PLAY_TONE, frequency)

    def connect(self, cmd_queue: Queue, animal: Optional[AnimalSubject] = None):
        self._last_x = None
        self._last_y = None
        self._last_z = None

        if self.tunnel_identifier == CAN_IDENTIFIER:
            # This is specific to wanting to be able to test UI changes w/the emulation interface, which is not
            # configured to generate messages as frequently as the real device.
            buffer_size = 10 if HAVE_CAN_DEVICE else 1
            self._tunnel_device = DeviceConnection(CanDevice(buffer_size=buffer_size), cmd_queue)
            self._tunnel_device.name = "can-tunnel"
        else:
            self._tunnel_device = DeviceConnection(HeadFix(port=self.tunnel_identifier, buffer_size=10), cmd_queue)
            self._tunnel_device.name = "serial-tunnel"

        if self.pellet_identifier == CAN_IDENTIFIER:
            if self.tunnel_identifier == CAN_IDENTIFIER:
                self._pellet_device = self._tunnel_device
                self._tunnel_device.name = "can-device"
            else:
                self._pellet_device = DeviceConnection(CanDevice(), cmd_queue)
                self._tunnel_device.name = "can-pellet"
        else:
            self._pellet_device = DeviceConnection(PelletDelivery(port=self.pellet_identifier), cmd_queue)
            self._tunnel_device.name = "serial-pellet"

        self._tunnel_device.request_connect()

        if self._pellet_device is not self._tunnel_device:
            self._pellet_device.request_connect()

        self._send_command(self._tunnel_device, SystemCommandKind.REQUEST_VERSION)

        if self._pellet_device is not self._tunnel_device:
            self._send_command(self._pellet_device, SystemCommandKind.REQUEST_VERSION)

        self._send_command(self._tunnel_device, SystemCommandKind.STREAM_START)

        if animal is not None:
            self.update_head_magnet_intensity(animal.baseline_magnet_intensity)
            self.set_x(animal.pellet_x)
            self.set_y(animal.pellet_y)
            self.set_z(animal.pellet_z)

    def disconnect(self):
        if self._tunnel_device is not None:
            self._tunnel_device.request_disconnect()
        if self._pellet_device is not None:
            self._pellet_device.request_disconnect()

        self._tunnel_device = None
        self._pellet_device = None

        self._on_property_changed(self.TUNNEL_VERSION_PROPERTY, "", None)
        self._on_property_changed(self.PELLET_VERSION_PROPERTY, "", None)

    def _message_handler_property_changed(self, name: str, value, old_value):
        if name == MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY:
            self._head_magnet_position = value
            self._on_property_changed(MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY, value, old_value)
        elif name == MessageHandler.DEVICE_X_PROPERTY:
            self._last_x = value
        elif name == MessageHandler.DEVICE_Y_PROPERTY:
            self._last_y = value
        elif name == MessageHandler.DEVICE_Y_PROPERTY:
            self._last_z = value
        elif name == MessageHandler.FIRMWARE_VERSION_PROPERTY and value is not None:
            version = str(value).lower()
            if version.find("module") != -1:
                version = version.replace("module", "").strip()
            if version.find("pellet") != -1:
                self._on_property_changed(self.PELLET_VERSION_PROPERTY, version.replace("pellet ", "").strip(),
                                          old_value)
            elif version.find("magnet") != -1:
                self._on_property_changed(self.TUNNEL_VERSION_PROPERTY, version.replace("magnet ", "").strip(),
                                          old_value)
            elif version.find("tunnel") != -1:
                self._on_property_changed(self.TUNNEL_VERSION_PROPERTY, version.replace("tunnel ", "").strip(),
                                          old_value)

    def _send_with_token(self, device: DeviceConnectionProtocol, cmd: SystemCommandKind, data=None) -> Optional[UUID]:
        token = uuid4()
        if self._send_command(device, cmd, data, token):
            return token
        else:
            return None

    # noinspection PyMethodMayBeStatic
    def _send_command(self, device: DeviceConnectionProtocol, cmd: SystemCommandKind, data=None, context=None) -> bool:
        if device is not None:
            device.send_message(cmd, data, context)
            return True

        return False
