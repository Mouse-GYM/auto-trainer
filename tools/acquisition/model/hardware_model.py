import math
import threading
import time
from queue import Queue
from uuid import UUID, uuid4
from typing import Optional, Tuple, Dict, Union

from autotrainer.core import (ObservableObject, SystemCommandKind, MessageHandler, AnimalSubject, Offset3DTuple,
                              get_verbose_logger, Motor)
from autotrainer.behavior import TunnelDeviceProtocol, PelletDeviceProtocol
from autotrainer.core.message import SystemDataArgsKwargs
from autotrainer.device import (DeviceConnectionProtocol, HAVE_CAN_DEVICE, DeviceConnection, CanDevice,
                                StepperConfig, ServoConfig)

logger = get_verbose_logger(__name__)

_nans_offset3dTuple = Offset3DTuple(math.nan, math.nan, math.nan)


class HardwareModel(ObservableObject, TunnelDeviceProtocol, PelletDeviceProtocol):
    TUNNEL_VERSION_PROPERTY = "tunnel_version"
    PELLET_VERSION_PROPERTY = "pellet_version"

    TUNNEL_IDENTIFIER_PROPERTY = "tunnel_identifier"
    PELLET_IDENTIFIER_PROPERTY = "pellet_identifier"

    PENDING_COMMAND_TOKEN_PROPERTY = "pending_command_token"
    PENDING_COMMAND_PROPERTY = "pending_command"

    FRONT_DOOR_PROPERTY = "front_door"
    SLIDE_DOOR_PROPERTY = "slide_door"

    def __init__(self, message_handler: MessageHandler):
        super().__init__()

        self._device: Optional[DeviceConnectionProtocol] = None

        self._pending_command: Optional[SystemCommandKind] = None
        self._pending_command_token: Optional[UUID] = None
        self._pending_command_perf_now: Optional[float] = None
        self._pending_tokens: Dict[UUID, Tuple[SystemCommandKind, float]] = {}

        message_handler.property_changed += self._message_handler_property_changed
        message_handler.ack_received += self._ack_received

        self._head_magnet_position: Optional[float] = None

        # Support for relative x, y, z movements and whether they are persistent as the Send position various between
        # hardware implementations. One the Alogus hardware is used exclusively, it should be possible to remove these
        # and rely on SET_X/Y/Z commands with the extra arguments that support relative and/or movements that should
        # not affect the Send position.
        self._last_coordinates = _nans_offset3dTuple
        self._last_set_coordinates = _nans_offset3dTuple  # what we've SET

        # what the motors report they've been SET (with possible drift corrected)
        self._send_coordinates = _nans_offset3dTuple

        self._front_door_open: bool = False
        self._slide_door_open: bool = False

        self._lock = threading.RLock()  # **required** re-entrant lock !!

    @property
    def pending_command_token(self) -> Optional[UUID]:
        return self._pending_command_token

    @pending_command_token.setter
    def pending_command_token(self, value: Optional[UUID]):
        self._pending_command_token = self._on_property_changed(HardwareModel.PENDING_COMMAND_TOKEN_PROPERTY, value,
                                                                self._pending_command_token)

    @property
    def pending_command(self) -> Optional[SystemCommandKind]:
        return self._pending_command

    @pending_command.setter
    def pending_command(self, value: Optional[SystemCommandKind]):
        self._pending_command = self._on_property_changed(HardwareModel.PENDING_COMMAND_PROPERTY, value,
                                                          self._pending_command)

    @property
    def last_position(self) -> Optional[Offset3DTuple]:
        return self._last_coordinates

    @property
    def last_set_position(self) -> Optional[Offset3DTuple]:
        value = self._last_set_coordinates
        if any(map(math.isnan, value)):
            return None
        return value

    @property
    def send_x(self):
        return self._send_coordinates.x

    @send_x.setter
    def send_x(self, value):
        prev, self._send_coordinates = self._send_coordinates, self._send_coordinates.replace(x=value)
        self._on_property_changed("send_x", value, prev.x)

    @property
    def send_y(self):
        return self._send_coordinates.y

    @send_y.setter
    def send_y(self, value):
        prev, self._send_coordinates = self._send_coordinates, self._send_coordinates.replace(y=value)
        self._on_property_changed("send_y", value, prev.y)

    @property
    def send_z(self):
        return self._send_coordinates.z

    @send_z.setter
    def send_z(self, value):
        prev, self._send_coordinates = self._send_coordinates, self._send_coordinates.replace(z=value)
        self._on_property_changed("send_z", value, prev.z)

    @property
    def front_door_open(self):
        return self._front_door_open

    @front_door_open.setter
    def front_door_open(self, value: bool):
        self._front_door_open = self._on_property_changed(HardwareModel.FRONT_DOOR_PROPERTY, value,
                                                          self._front_door_open)

    @property
    def slide_door_open(self):
        return self._slide_door_open

    @slide_door_open.setter
    def slide_door_open(self, value: bool):
        self._slide_door_open = self._on_property_changed(HardwareModel.SLIDE_DOOR_PROPERTY, value,
                                                          self._slide_door_open)

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
        if value != self._head_magnet_position:
            logger.verbose("sending move magnet to %.3f", value)
            # self._head_magnet_position = value  # this is set from reading the hardware status
            return self._send_with_token(self._device, SystemCommandKind.MOVE_MAGNET_SERVO,
                                         value)
        logger.debug("head magnet currently already at pos %.3f", value)
        return None

    def open_tunnel_gate(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.OPEN_TUNNEL_GATE)

    def close_tunnel_gate(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.CLOSE_TUNNEL_GATE)

    def tare_load_cell(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.UPDATE_SCALE_TARE)

    def _set_axis(self, value: float, *, absolute: bool = True,
                  system_set_cmd: SystemCommandKind, coord_idx: int) -> Optional[UUID]:
        prev_value = self._last_set_coordinates[coord_idx]
        if absolute:
            new_value = value
        else:
            if math.isnan(prev_value):
                err_msg = (
                    f"Cannot SET axis with relative value when SET not already called/initialized with absolute value"
                )
                raise ValueError(err_msg)
            new_value = prev_value + value
        coord_char = "xyz"[coord_idx]
        if new_value < 0:
            value = 0 if absolute else -prev_value
            new_value = 0
            logger.debug("Axis-%s: limited move to 0 ; value=%.3f absolute=%s",
                         "XYZ"[coord_idx], value, absolute)
        self._on_property_changed(f"set_{coord_char}", new_value, prev_value)
        self._last_set_coordinates = self._last_set_coordinates.replace(**{coord_char: new_value})
        return self._send_with_token(self._device, system_set_cmd,
                                     SystemDataArgsKwargs(value, relative=not absolute))

    def set_x(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        return self._set_axis(value, absolute=absolute, system_set_cmd=SystemCommandKind.SET_X, coord_idx=0)

    def set_y(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        return self._set_axis(value, absolute=absolute, system_set_cmd=SystemCommandKind.SET_Y, coord_idx=1)

    def set_z(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        return self._set_axis(value, absolute=absolute, system_set_cmd=SystemCommandKind.SET_Z, coord_idx=2)

    def _move_axis(self, value: float, *, absolute: bool = True,
                   system_move_cmd: SystemCommandKind, coord_idx: int) -> Optional[UUID]:
        prev_value = self._last_coordinates[coord_idx]
        if not absolute:
            if math.isnan(prev_value):
                logger.warning("Axis-%s: relative movement requested, but no previous position is set",
                               "XYZ"[coord_idx])
                return None
            value += prev_value
        coord_char = "xyz"[coord_idx]
        self._last_coordinates = self._last_coordinates.replace(**{coord_char: value})
        return self._send_with_token(self._device, system_move_cmd, value)

    def move_x(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        return self._move_axis(value, absolute=absolute, system_move_cmd=SystemCommandKind.MOVE_X, coord_idx=0)

    def move_y(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        return self._move_axis(value, absolute=absolute, system_move_cmd=SystemCommandKind.MOVE_Y, coord_idx=1)

    def move_z(self, value: float, *, absolute: bool = True) -> Optional[UUID]:
        return self._move_axis(value, absolute=absolute, system_move_cmd=SystemCommandKind.MOVE_Z, coord_idx=2)

    def send_to_limits(self):
        return self._send_with_token(self._device, SystemCommandKind.SEND_TO_LIMITS,
                                     [Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR, Motor.PELLET_X_MOTOR])

    def send_retract(self):
        return self._send_with_token(self._device, SystemCommandKind.SEND_RETRACT)

    def send_home(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.SEND_HOME)

    def load_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.LOAD_PELLET)

    def send_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.SEND_PELLET)

    def release_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.RELEASE_PELLET)

    def cover_pellet(self) -> Optional[UUID]:
        return self._send_with_token(self._device, SystemCommandKind.COVER_PELLET)

    def play_tone(self, frequency: int, duration: float) -> Optional[UUID]:
        """Play a tone
        :param frequency: in Hz (integer)
        :param duration: in seconds (float)
        """
        duration_ms = int(duration * 1000)
        return self._send_with_token(self._device, SystemCommandKind.PLAY_TONE, (frequency, duration_ms))

    def delay(self, amount: float):
        return self._send_with_token(self._device, SystemCommandKind.DELAY, amount)

    def connect(self, cmd_queue: Queue, animal: Optional[AnimalSubject] = None):
        self._last_coordinates = _nans_offset3dTuple
        self._last_set_coordinates = _nans_offset3dTuple

        # This is specific to wanting to be able to test UI changes w/the emulation interface, which is not
        # configured to generate messages as frequently as the real device.
        buffer_size = 10 if HAVE_CAN_DEVICE else 1
        self._device = DeviceConnection(CanDevice(buffer_size=buffer_size), cmd_queue)
        self._device.name = "can-device"

        self._device.request_connect()

        if self._device is not self._device:
            self._device.request_connect()

        self._send_command(self._device, SystemCommandKind.REQUEST_VERSION)

        if self._device is not self._device:
            self._send_command(self._device, SystemCommandKind.REQUEST_VERSION)

        # load and set motors and move configs
        self._device.load_default_motor_config()
        self._device.load_default_move_config()

        self._send_command(self._device, SystemCommandKind.STREAM_START)

        self._send_command(self._device, SystemCommandKind.UPDATE_SCALE_TARE)

        self.send_home()

        if animal is not None:
            self.delay(0.5)
            self.update_head_magnet_intensity(animal.baseline_magnet_intensity)
            # self._send_command(self._device, SystemCommandKind.MOVE_MAGNET_SERVO,
            #                    animal.baseline_magnet_intensity)
            self.set_x(animal.pellet_x)
            self.set_z(animal.pellet_z)
            self.set_y(animal.pellet_y)
            self.send_pellet()

    def disconnect(self):
        if self._device is not None:
            self._device.request_disconnect()

        self._device = None

        self._on_property_changed(self.TUNNEL_VERSION_PROPERTY, "", None)
        self._on_property_changed(self.PELLET_VERSION_PROPERTY, "", None)

    def _message_handler_property_changed(self, name: str, value, old_value):
        if name == MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY:
            self._head_magnet_position = self._on_property_changed(MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY, value,
                                                                   self._head_magnet_position)
        elif name == MessageHandler.STEPPER_X_PROPERTY:
            self._last_coordinates = self._last_coordinates.replace(x=value.position)
            self.send_x = value.send_position
        elif name == MessageHandler.STEPPER_Y_PROPERTY:
            self._last_coordinates = self._last_coordinates.replace(y=value.position)
            self.send_y = value.send_position
        elif name == MessageHandler.STEPPER_Z_PROPERTY:
            self._last_coordinates = self._last_coordinates.replace(z=value.position)
            self.send_z = value.send_position
        elif name == MessageHandler.FRONT_DOOR_PROPERTY:
            self.front_door_open = value
        elif name == MessageHandler.DRAWER_DOOR_PROPERTY:
            self.slide_door_open = value
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
        with self._lock:
            # ensure only 1 command can be sent at the same time
            # NB: there are multiple threads which can act on this instance,
            # and we don't want 2 to try send a message at the same time,
            # or the pending command token might be overwritten.
            return self.__send_with_token(device, cmd, data)

    def __send_with_token(self, device: DeviceConnectionProtocol, cmd: SystemCommandKind, data=None) -> Optional[UUID]:
        perf_now = time.perf_counter()
        expired_tokens = set()
        for pending_token, (pending_cmd, pending_t_perf) in self._pending_tokens.items():
            age_second = perf_now - pending_t_perf
            if age_second > 30:
                logger.warning("Giving up on pending cmd %s for too long ; token=%s age=%s seconds",
                               pending_cmd, pending_token, age_second)
                expired_tokens.add(pending_token)
        for expired in expired_tokens:
            self._pending_tokens.pop(expired, None)

        token = uuid4()
        logger.debug("send_command cmd=%s token=%s nbr=%s", cmd, token, len(self._pending_tokens))
        if self._send_command(device, cmd, data, token):
            self._pending_tokens[token] = (cmd, perf_now)
            return token
        else:
            logger.verbose("send_command failed, device not setup yet: cmd=%s token=%s", cmd, token)
            return None

    # noinspection PyMethodMayBeStatic
    def _send_command(self, device: DeviceConnectionProtocol, cmd: SystemCommandKind, data=None, context=None) -> bool:
        if device is not None:
            device.send_message(cmd, data, context)
            return True

        return False

    def set_motors_drift(self, drift: Offset3DTuple):
        """Apply the pellet motor drift"""
        dev = self._device
        if dev is None:
            return
        dev.send_message(SystemCommandKind.SET_MOTOR_DRIFT, drift)
        # self._device.device.device_interface.set_motors_drift(drift)
        # this ensure the next send_to_fixed_pos command will get the corrected position:
        for cmd_kind in (SystemCommandKind.SET_X, SystemCommandKind.SET_Y, SystemCommandKind.SET_Z):
            dev.send_message(cmd_kind, SystemDataArgsKwargs(0, relative=True))

    def set_auto_correct_motor_drift(self, enabled: bool):
        dev = self._device
        if dev is not None:
            dev.send_message(SystemCommandKind.SET_AUTO_CORRECT_DRIFT, enabled)
            if not enabled:
                logger.verbose("Doing SET_X/Y/Z relative=0 to clear possible motors drift")
                for cmd_kind in (SystemCommandKind.SET_X, SystemCommandKind.SET_Y, SystemCommandKind.SET_Z):
                    dev.send_message(cmd_kind, SystemDataArgsKwargs(0, relative=True))

    def _ack_received(self, token: UUID):
        if token is not None and token not in self._pending_tokens:
            logger.warning("pending_token != ack_received token: %s vs pending_tokens=%s",
                           token, self._pending_tokens)
        else:
            self._pending_tokens.pop(token, None)

    def wait_pending_command_acked(self, token, timeout: float = 3):
        t_perf_start = time.perf_counter()
        timeout = t_perf_start + timeout
        while True:
            t_perf = time.perf_counter()
            if t_perf >= timeout:
                break
            if token not in self._pending_tokens:
                logger.verbose("Got ack for token=%s ; delay=%.6f", token, t_perf - t_perf_start)
                return
            time.sleep(0.005)
        raise RuntimeError(f"timeout waiting ack of pending token={token}")

    def get_motor_config(self, motor: Motor) -> Union[StepperConfig, ServoConfig]:
        return self._device.device.device_interface.get_motor_configuration(motor)
