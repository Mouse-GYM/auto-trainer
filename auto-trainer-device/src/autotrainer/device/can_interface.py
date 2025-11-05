"""
Interface to the CANbus protocol to the device.

The interface to the CANbus is via a C++ library which provides high-level
functionality to the device (e.g. set a configuration, move a motor).

Data read from the CANbus is in the form of a JerryCANMsg class. That class is
translated to a more generic data class (see device_interface.py) for the rest
of the application to consume.

Writes to the device can be from almost any threaded context. Note that the low-level
CAN driver handles thread safety. Reads occur in the device_thread context, returning
a list of data sets that are then propagated to the rest of the application.
"""

import logging
import inspect
import time
import warnings
from enum import Enum, IntEnum
from operator import attrgetter
from typing import Type, Optional, Dict, Union, Any, Tuple

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, AbsOrRel, \
        JerryCANBootloaderCmd
except ModuleNotFoundError:
    JerryCAN = None
else:
    from importlib.metadata import version
    jerry_v = tuple(
        map(lambda s: int(s) if s.isdigit() else s, version("pyjerrycan").split("."))
    )
    if jerry_v < (1, 2, 0):
        warnings.warn(f"expected pyjerrycan >= 1.2.0 ; got {jerry_v}", UserWarning)


from autotrainer.core.logging import get_verbose_logger
from .device_interface import (
    DeviceInterface,
    Acknowledge,
    AnalogOutput,
    AnalogOutputs,
    AudioData,
    DoorData,
    Heartbeat,
    LoadCellReading,
    PressureReading,
    Motor,
    DigitalOutputs,
    Source,
    Status,
    Target,
    Tone,
    ColorLed,
    MagnetDigitalInputs,
    MotorSource,
    PelletDigitalInputs,
    ServoConfig,
    StepperConfig,
    SensorStatus,
    ServoStatus,
    StepperStatus,
    Version,
)
from .stepper_motor import mm_to_turns, turns_to_mm


logger = get_verbose_logger(__name__)


_STEPPER_MAX_TURNS = 15  # absolute max nbr of turns for each stepper, hardcoded for now.
_STEPPER_MAX_POS = turns_to_mm(_STEPPER_MAX_TURNS)


def _is_pellet_by_addr(addr: int) -> bool:
    """
    Pellet device CAN address board type is 0 (bits 2 and 3)

    Args:
        addr: Physical CAN address

    Returns:
        bool: True if the address is associated with a pellet device
    """
    return addr & 0xC == 0


def _is_magnet_by_addr(addr: int) -> bool:
    """
    Pellet device CAN address board type is 4 (bits 2 and 3)

    Args:
        addr: Physical CAN address

    Returns:
        bool: True if the address is associated with a manget/head device
    """
    return addr & 0xC == 0x04


def _addr2tgt(addr: int) -> Target:
    """
    Convert a CANbus address to a target

    Args:
        addr: Physical CAN address

    Returns:
        Target: Either PELLET_DEVICE or MAGNET_DEVICE
    """
    return Target.PELLET_DEVICE if _is_pellet_by_addr(addr) else Target.MAGNET_DEVICE


def target_to_str(target: Target) -> str:
    """
    Args:
        target: type of physical remote HW target

    Returns:
        str: Human-readable string identifier for the target
    """
    if target == Target.PELLET_DEVICE:
        return "Pellet"
    elif target == Target.MAGNET_DEVICE:
        return "Magnet"
    else:
        return "Unknown"


_MOTOR_TO_STR_MAP = {
    Motor.PELLET_X_MOTOR: "X",
    Motor.PELLET_Y_MOTOR: "Y",
    Motor.PELLET_Z_MOTOR: "Z",
    Motor.TUNNEL_MAGNET_SERVO: "Magnet",
    Motor.PELLET_LOAD_SERVO: "Load",
    Motor.PELLET_COVER_SERVO: "Cover",
    Motor.TUNNEL_GATE_SERVO: "Gate"
}


def motor_to_str(motor: Motor) -> str:
    """
    Args:
        motor: motor (servo or stepper) identifier

    Returns:
        str: Human-readable string identifier for the motor
    """
    return _MOTOR_TO_STR_MAP.get(motor, "Unknown")


class MotorInstance(IntEnum):
    TUNNEL_MAGNET_SERVO_ID = 0
    TUNNEL_GATE_SERVO_ID = 1
    PELLET_X_MOTOR_ID = 0
    PELLET_Y_MOTOR_ID = 1
    PELLET_Z_MOTOR_ID = 2
    PELLET_COVER_SERVO_ID = 0
    PELLET_LOAD_SERVO_ID = 1


_MOTOR_TO_ID_MAP = {
    Motor.PELLET_X_MOTOR: MotorInstance.PELLET_X_MOTOR_ID,
    Motor.PELLET_Y_MOTOR: MotorInstance.PELLET_Y_MOTOR_ID,
    Motor.PELLET_Z_MOTOR: MotorInstance.PELLET_Z_MOTOR_ID,
    Motor.TUNNEL_MAGNET_SERVO: MotorInstance.TUNNEL_MAGNET_SERVO_ID,
    Motor.TUNNEL_GATE_SERVO: MotorInstance.TUNNEL_GATE_SERVO_ID,
    Motor.PELLET_LOAD_SERVO: MotorInstance.PELLET_LOAD_SERVO_ID,
    Motor.PELLET_COVER_SERVO: MotorInstance.PELLET_COVER_SERVO_ID
}


def _motor_to_id(motor: Motor) -> int:
    """
    Args:
        motor: Motor identifier

    Returns:
        int: Physical identifier for the motor
    """

    motor_id = _MOTOR_TO_ID_MAP[motor]
    return motor_id.value

_motor_to_axis_idx_map = {
    Motor.PELLET_X_MOTOR: 0,
    Motor.PELLET_Y_MOTOR: 1,
    Motor.PELLET_Z_MOTOR: 2,
}
def _motor_to_axis_idx(
    motor: Motor,
    *,
    _map=_motor_to_axis_idx_map,  # noqa
) -> int:
    value = _map.get(motor, None)
    if value is None:
        raise ValueError(f"Invalid motor for offset idx map: {motor}")
    return value


_servo_motors = {
    Motor.TUNNEL_MAGNET_SERVO,
    Motor.TUNNEL_GATE_SERVO,
    Motor.PELLET_LOAD_SERVO,
    Motor.PELLET_COVER_SERVO,
}

def is_servo(motor: Motor,
             *,
             _servo_motors=_servo_motors,  # noqa
             ) -> bool:
    """
    Args:
        motor: motor identifier

    Returns:
        bool: True if the motor is a servo motor, False otherwise
    """
    return motor in _servo_motors


def is_stepper(motor: Motor) -> bool:
    """
    Args:
        motor: motor identifier

    Returns:
        bool: True if the motor is a stepper motor, False otherwise
    """
    return not is_servo(motor)


_tunnel_servos = {
    Motor.TUNNEL_MAGNET_SERVO,
    Motor.TUNNEL_GATE_SERVO,
}

def target_of_motor(motor: Motor,
                    *,
                    _tunnel_servos=_tunnel_servos,  # noqa
                    ) -> Target:
    """
    Args:
        motor: motor identifier

    Returns:
        Target: the hardware target that the motor resides on
    """
    return (
        Target.MAGNET_DEVICE if motor in _tunnel_servos
        else Target.PELLET_DEVICE
    )


def _id_to_motor(target: Target, isa_servo: bool, motor_id: int) -> Motor:
    """
    Convert a motor identifier from a CAN message to a Motor identifier

    Args:
        target: target from whence the id came from
        isa_servo: True if the motor is a servo
        motor_id: CAN message motor id

    Returns:
        Motor: associated Motor identifier
    """

    # NOTE: The ENUM.value MUST be used here, as the incoming value is an int,
    # and we need to compare to the value of the enum, not the enum, itself.

    if target == Target.MAGNET_DEVICE:
        if isa_servo:
            if motor_id == MotorInstance.TUNNEL_MAGNET_SERVO_ID:
                return Motor.TUNNEL_MAGNET_SERVO
            elif motor_id == MotorInstance.TUNNEL_GATE_SERVO_ID:
                return Motor.TUNNEL_GATE_SERVO
    else:
        if isa_servo:
            if motor_id == MotorInstance.PELLET_COVER_SERVO_ID:
                return Motor.PELLET_COVER_SERVO
            elif motor_id == MotorInstance.PELLET_LOAD_SERVO_ID:
                return Motor.PELLET_LOAD_SERVO
        else:
            if motor_id == MotorInstance.PELLET_X_MOTOR_ID:
                return Motor.PELLET_X_MOTOR
            elif motor_id == MotorInstance.PELLET_Y_MOTOR_ID:
                return Motor.PELLET_Y_MOTOR
            elif motor_id == MotorInstance.PELLET_Z_MOTOR_ID:
                return Motor.PELLET_Z_MOTOR

    return Motor.NONE


class CanInterface(DeviceInterface):
    """
    CanInterface implements the details of
        * communication (read and write) with Alogus hardware interface (pyjerrcan)

    Applications and scripts would generally not interact with this class directly,
    but with the more generalized behavior in the CanDevice class.
    """

    # UUIDs are used in a command/acknowledge protocol to know when a command is complete
    # A UUID of 0 is an invalid UUID.
    # UUIDs in the CAN message are 8 bits, so UUIDs here are maintained to 8 bits
    _uuid: int = 1

    @classmethod
    def next_uuid(cls) -> int:
        """
        Returns:
            int: Next UUID to use
        """
        # TODO: we should randomize the uuid we use to pass to our CAN messages,
        #  this would prevent possible conflict with a second client connected on the bus.
        cls._uuid = cls._uuid + 1 & 0xFF  # maintain 8 bits
        if cls._uuid == 0:  # don't allow 0's
            cls._uuid = 1
        if __debug__:
            # Get the current stack frame
            current_frame = inspect.currentframe()
            # Get the frame of the caller (one level up)
            caller_frame = current_frame.f_back
            # Extract the code object from the caller's frame
            caller_code = caller_frame.f_code
            # Get the name of the function from the code object
            caller_name = caller_code.co_name
            logger.debug("next_uuid: caller=%s uuid=%s", caller_name, cls._uuid)
        return cls._uuid

    @classmethod
    def uuid(cls) -> int:
        """
        Returns:
            int: UUID of active command
        """
        return cls._uuid

    def __init__(self):
        """
        Initialize the CanInterface Class.

        Creates default Configurations for motors. Expected to be updated during
        the connection protocol.

        Sets known pellet and magnet address to None. Expected to be updated during
        the connection protocol.
        """
        super().__init__()

        if JerryCAN is None:
            self._jc = None
        else:
            self._jc = JerryCAN()

        # by default, will be set in open() too
        self._read_msgs = self._read_by_one_msg
        self._get_timestamp_ns = self._assign_timestamp_ns
        self._get_index = lambda m: time.perf_counter_ns()

        self._cnt_none = 0
        self._is_open = False

        self._pellet_addr: Optional[int] = None
        self._magnet_addr: Optional[int] = None

        self.magnet_config = ServoConfig()
        self.gate_config = ServoConfig()
        self.load_config = ServoConfig()
        self.cover_config = ServoConfig()

        self._motor_configs = {}
        self.x_config = StepperConfig()
        self.y_config = StepperConfig()
        self.z_config = StepperConfig()

        self._audio = AudioData()

        self.load_cell_factor = 21053.0

        no_op = lambda msg: None

        self._last_positions: Dict[Motor, Optional[float]] = {
            Motor.PELLET_X_MOTOR: None,
            Motor.PELLET_Y_MOTOR: None,
            Motor.PELLET_Z_MOTOR: None,
        }

        # Simple handlers implemented as lambdas
        self._handlers = {
            JerryCANCmdType.HEARTBEAT: lambda msg: Heartbeat(target=_addr2tgt(msg.dst_id)),
            JerryCANCmdType.BOOTLOADER_RESPONSE: self._translate_bootloader,
            JerryCANCmdType.CFG_RESPONSE: self._translate_config,
            JerryCANCmdType.GPIO_READ: self._translate_gpio,
            JerryCANCmdType.TONE: lambda msg: Tone(
                target=_addr2tgt(msg.dst_id),
                time_remaining_ms=msg.tone.duration_ms,
                frequency_hz=msg.tone.frequency_hz
            ),
            JerryCANCmdType.ANALOG_OUT: self._translate_analog_out,
            JerryCANCmdType.LOAD_CELL_READ: lambda msg: LoadCellReading(
                target=_addr2tgt(msg.dst_id),
                load=float(msg.load_cell_read.load_mv) / 1000.0 * self.load_cell_factor,
            ),
            JerryCANCmdType.PRESSURE_READ: lambda msg: PressureReading(
                target=_addr2tgt(msg.dst_id),
                pressure=float(msg.pressure_read.pressure)
            ),
            JerryCANCmdType.RGB_LED: lambda msg: ColorLed(
                target=_addr2tgt(msg.dst_id),
                red=msg.rgb_led.red,
                green=msg.rgb_led.green,
                blue=msg.rgb_led.blue
            ),
            JerryCANCmdType.AUDIO_MAGNITUDE_DATA_BEGIN: self._handle_audio_begin,
            JerryCANCmdType.AUDIO_MAGNITUDE_DATA_CONT: self._handle_audio_cont,
            JerryCANCmdType.AUDIO_MAGNITUDE_DATA_END: self._handle_audio_end,
            JerryCANCmdType.DOOR_SENSOR: self._translate_door_sensor,
            JerryCANCmdType.SERVO_STATUS: self._translate_servo_status,
            JerryCANCmdType.STEPPER_STATUS: self._handle_stepper_status,
            JerryCANCmdType.TEMP_HUM_READ: lambda msg: SensorStatus(
                target=_addr2tgt(msg.dst_id),
                temperature_c=float(msg.temp_hum_read.temperature) / 100.0,
                humidity_percent=float(msg.temp_hum_read.humidity) / 100.0
            ),
            JerryCANCmdType.ACKNOWLEDGE: lambda msg: Acknowledge(uuid=msg.uuid),
            # no-op handlers, to silence the warning if unknown message type
            JerryCANCmdType.STEPPER_HOME: no_op,
            JerryCANCmdType.STEPPER_MOVE: no_op,
            JerryCANCmdType.CFG_WRITE: no_op,
            JerryCANCmdType.SERVO_MOVE: no_op,
            JerryCANCmdType.GPIO_WRITE: no_op,
            JerryCANCmdType.DELAY: no_op,
        }

    @property
    def magnet_config(self):
        """
        Returns:
            Handle to the magnet servo configuration
        """
        return self._magnet_config

    @magnet_config.setter
    def magnet_config(self, config: ServoConfig):
        """
        Updates the magnet servo configuration (local copy)

        Args:
            config: new configuration
        """
        self._magnet_config = config if config is not None else ServoConfig()
        self._magnet_config.motor = Motor.TUNNEL_MAGNET_SERVO
        self._magnet_config.target = target_of_motor(self._magnet_config.motor)

    @property
    def gate_config(self):
        """
        Returns:
            Handle to the gate servo configuration
        """
        return self._gate_config

    @gate_config.setter
    def gate_config(self, config: ServoConfig):
        """
        Updates the gate servo configuration (local copy)

        Args:
            config: new configuration
        """
        self._gate_config = config if config is not None else ServoConfig()
        self._gate_config.motor = Motor.TUNNEL_GATE_SERVO
        self._gate_config.target = target_of_motor(self._gate_config.motor)

    @property
    def load_config(self):
        """
        Returns:
            Handle to the load arm servo configuration
        """
        return self._load_config

    @load_config.setter
    def load_config(self, config: ServoConfig):
        """
        Updates the load arm servo configuration (local copy)

        Args:
            config: new configuration
        """
        self._load_config = config if config is not None else ServoConfig()
        self._load_config.motor = Motor.PELLET_LOAD_SERVO
        self._load_config.target = target_of_motor(self._load_config.motor)

    @property
    def cover_config(self):
        """
        Returns:
            Handle to the cover servo configuration
        """
        return self._cover_config

    @cover_config.setter
    def cover_config(self, config: ServoConfig):
        """
        Updates the cover servo configuration (local copy)

        Args:
            config: new configuration
        """
        self._cover_config = config if config is not None else ServoConfig()
        self._cover_config.motor = Motor.PELLET_COVER_SERVO
        self._cover_config.target = target_of_motor(self._cover_config.motor)

    def _set_motor_config(self, config):
        config.target = target_of_motor(config.motor)
        self._motor_configs[config.motor] = config

    @property
    def x_config(self):
        """
        Returns:
            Handle to the X stepper motor configuration
        """
        return self._motor_configs[Motor.PELLET_X_MOTOR]

    @x_config.setter
    def x_config(self, config: StepperConfig):
        """
        Updates the X stepper motor configuration (local copy)

        Args:
            config: new configuration
        """
        config = config if config is not None else StepperConfig()
        config.motor = Motor.PELLET_X_MOTOR
        self._set_motor_config(config)

    @property
    def y_config(self):
        """
        Returns:
            Handle to the Y stepper motor configuration
        """
        return self._motor_configs[Motor.PELLET_Y_MOTOR]

    @y_config.setter
    def y_config(self, config: StepperConfig):
        """
        Updates the Y stepper motor configuration (local copy)

        Args:
            config: new configuration
        """
        config = config if config is not None else StepperConfig()
        config.motor = Motor.PELLET_Y_MOTOR
        self._set_motor_config(config)

    @property
    def z_config(self):
        """
        Returns:
            Handle to the Z stepper motor configuration
        """
        return self._motor_configs[Motor.PELLET_Z_MOTOR]

    @z_config.setter
    def z_config(self, config: StepperConfig):
        """
        Updates the Z stepper motor configuration (local copy)

        Args:
            config: new configuration
        """
        config = config if config is not None else StepperConfig()
        config.motor = Motor.PELLET_Z_MOTOR
        self._set_motor_config(config)

    @property
    def pellet_address(self):
        return self._pellet_addr

    @pellet_address.setter
    def pellet_address(self, addr: int):
        """
        Set the pellet CAN address. Used primarily for testing, as after data is received
        from the device(s), the address for each target will be updated automatically.

        Args:
            addr: Pellet CAN address
        """
        self._pellet_addr = addr
        logger.info(f"pellet module located at {self._pellet_addr}")

    @property
    def magnet_address(self):
        return self._magnet_addr

    @magnet_address.setter
    def magnet_address(self, addr: int):
        """
        Set the magnet CAN address. Used primarily for testing, as after data is received
        from the device(s), the address for each target will be updated automatically.

        Args:
            addr: Magnet CAN address
        """
        self._magnet_addr = addr
        logger.info(f"magnet module located at {self._magnet_addr}")

    @property
    def load_cell_factor(self):
        return self._load_cell_factor

    @load_cell_factor.setter
    def load_cell_factor(self, factor: float):
        self._load_cell_factor = factor

    def are_addresses_valid(self) -> bool:
        """
        Returns:
             bool: True if both the magnet and pellet CANbus addresses are valid
        """
        return self.magnet_address is not None and self.pellet_address is not None

    def _tgt2addr(self, target: Target) -> int:
        """
        Args:
            target

        Returns:
             int: CANbus address of the given target
        """
        dst = self.pellet_address if target == Target.PELLET_DEVICE else self.magnet_address
        return dst

    def _assign_address(self, message):
        """
        Assign the pellet or magnet CANbus address based on an incoming message. Each
        target address is set only once.

        Args:
            message: Jerrycan message
        """
        if self.pellet_address is None and _is_pellet_by_addr(message.dst_id):
            self.pellet_address = message.dst_id

        if self.magnet_address is None and _is_magnet_by_addr(message.dst_id):
            self.magnet_address = message.dst_id

    @property
    def is_open(self) -> bool:
        """
        Returns:
            bool: Connection to hardware is open (True) or closed (False)
        """
        return self._is_open

    def open(self) -> bool:
        """
        Open the interface (CANbus) connection

        Returns:
            bool: True if success False otherwise
        """
        if self._jc is None:
            return False

        self._is_open = self._jc.Open() == 0

        self._read_msgs = self._jc.ReceiveMessages if hasattr(self._jc, "ReceiveMessages") else self._read_by_one_msg
        self._get_timestamp_ns = attrgetter("timestamp_ns") if hasattr(JerryCANMsg, "timestamp_ns") else self._assign_timestamp_ns
        self._get_index = attrgetter("index") if hasattr(JerryCANMsg, "index") else (lambda _: time.perf_counter_ns())
        logger.debug("Using %s and %s and %s", self._read_msgs, self._get_timestamp_ns, self._get_index)

        self._cnt_none = 0
        if self._is_open:
            tot_flushed = 0
            t_end = time.perf_counter() + 1.5
            while True:
                flushed = self._read_msgs(100, collect_ms=5)  # purge whatever is available
                tot_flushed += len(flushed)
                for msg in flushed:
                    self._assign_address(msg)
                    if self.pellet_address is not None and self.magnet_address is not None:
                        break
                if self.pellet_address is not None and self.magnet_address is not None:
                    break
                if time.perf_counter() > t_end:
                    logger.critical("Could not obtain both pellet and magnet CAN bus addresses in time, "
                                    "either one or both of them is/are shutdown, "
                                    "either there is a CAN bus or CAN system related issue. "
                                    "You shall restart the app if/when that's corrected.")
                    break
            logger.notice("pellet_address=%s magnet_address=%s ; flushed %s",
                        self.pellet_address, self.magnet_address, tot_flushed)
            self._query_configuration()
        return self._is_open

    def close(self):
        """
        Close the interface (CANbus) connection
        """
        if self._is_open:
            self._jc.Close()

    def can_read(self) -> bool:
        """
        Returns:
            bool: True if Data can be read from the connection else False
        """
        return self._is_open

    def _read_by_one_msg(self, max_count: int, collect_ms: int):
        t_end = time.perf_counter() + collect_ms / 1000
        messages = []
        while True:
            msg = self._jc.ReceiveMessage()
            if msg is None:
                if collect_ms == 0 or time.perf_counter() > t_end:
                    return messages
            else:
                messages.append(msg)
            if 0 < max_count <= len(messages):
                return messages

    def read(self, max_count: int = 1, *, collect_ms: int = 0) -> Any:
        """
        Read a set of packets from the CANbus.

        Args:
            max_count: Maximum number of messages to return
            collect_ms: Maximum duration to read messages ; if <= 0 only read while message are read,
              on first non-available message: return what was already obtained.

        Returns:
            a list of data classes (see device_interface.py for list of classes)
        """
        if self._is_open:
            messages = self._read_msgs(max_count, collect_ms)
            if len(messages) == 0:
                self._cnt_none += 1
        else:
            messages = []
        # some handlers can return None, so we have to filter:
        return list(filter(lambda v: v is not None, map(self._translate, messages)))

    def write(self, value: Any) -> int:
        """
        Do not allow the application to write unknown messages to the CANbus

        Args:
            value

        Raises:
            NotImplementedError
        """
        raise NotImplementedError()

    def write_str(self, value: str) -> int:
        """
        Do not allow the application to write unknown messages to the CANbus

        Args:
            value

        Raises:
            NotImplementedErrord
        """
        raise NotImplementedError()

    def get_response(
        self,
        typeof: Type[MotorSource],
        target: Target,
        *,
        motor: Optional[Motor],
        timeout: float = 2.0):
        """
        Read data until a specific response is detected

        Args:
            typeof: Class name to look for
            target: Source target (Pellet or Magnet)
            motor: Optional motor to check against too
            timeout: Maximum time to wait (sec). Default=2.0
        """
        perf_timeout = time.perf_counter() + timeout
        final_res = None
        dropped = set()
        tot_dropped = 0
        logger.debug("get_response: typeof=%s target=%s motor=%s", typeof, target, motor)
        while time.perf_counter() < perf_timeout:
            messages = self.read(15, collect_ms=5)
            if len(messages) == 0:
                self._cnt_none += 1
                continue
            # loop reversed, given we break and so that we return the most recent one:
            for msg in reversed(messages):
                if isinstance(msg, typeof):
                    # logger.debug("got msg of typeof ; msg.target=%s msg.motor=%s", msg.target, msg.motor)
                    if (
                        msg.target == target
                        and (motor is None or msg.motor == motor)
                    ):
                        final_res = msg
                        break
                dropped.add(type(msg))
                tot_dropped += 1
            if final_res is not None:
                break

        logger.debug("get_response(%s): res=%s ; dropped %s msgs, types=%s",
                     typeof.__qualname__, final_res, tot_dropped, dropped)

        return final_res

    def get_motor_configuration(self, motor: Motor) -> Union[ServoConfig, StepperConfig]:
        """
        Args:
            motor

        Returns:
             ServoConfig or StepperConfig: The configuration for the given motor
        """
        if is_servo(motor):

            # Not all configuration items get pushed/pulled to the target
            # Reminder: config points to same object after assignment
            if motor == Motor.PELLET_COVER_SERVO:
                config = self.cover_config
            elif motor == Motor.PELLET_LOAD_SERVO:
                config = self.load_config
            elif motor == Motor.TUNNEL_MAGNET_SERVO:
                config = self.magnet_config
            elif motor == Motor.TUNNEL_GATE_SERVO:
                config = self.gate_config
            else:
                logger.warning("Unknown motor servo config requested: motor=%s", motor)
                config = ServoConfig()
        else:
            assert is_stepper(motor)
            if motor == Motor.PELLET_X_MOTOR:
                config = self.x_config
            elif motor == Motor.PELLET_Y_MOTOR:
                config = self.y_config
            elif motor == Motor.PELLET_Z_MOTOR:
                config = self.z_config
            else:
                logger.warning("Unknown motor stepper config requested: motor=%s", motor)
                config = StepperConfig()

        return config

    def set_motor_configuration(self, motor: Motor, config, write_to_remote: bool = True) -> bool:
        """
        Set a motor's configuration.

        Args:
            motor - Motor associated with the configuration
            config - Configuration data
            write - Indication to push data to target (True), or locally store new configuration (False)

        Returns:
            bool: True if successful else False
        """
        if config is None:
            return False

        rc = False

        config.motor = motor

        if motor == Motor.TUNNEL_MAGNET_SERVO:
            self.magnet_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.magnet_config)

        elif motor == Motor.TUNNEL_GATE_SERVO:
            self.gate_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.gate_config)

        elif motor == Motor.PELLET_X_MOTOR:
            self.x_config = config
            if write_to_remote:
                rc = self._write_stepper_config(self.x_config)

        elif motor == Motor.PELLET_Y_MOTOR:
            self.y_config = config
            if write_to_remote:
                rc = self._write_stepper_config(self.y_config)

        elif motor == Motor.PELLET_Z_MOTOR:
            self.z_config = config
            if write_to_remote:
                rc = self._write_stepper_config(self.z_config)

        elif motor == Motor.PELLET_COVER_SERVO:
            self.cover_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.cover_config)

        elif motor == Motor.PELLET_LOAD_SERVO:
            self.load_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.load_config)

        return rc

    def _query_motor_configuration(
        self,
        motor: Motor,
        config_type: Type[MotorSource],
        *,
        timeout: float = 0.5,
    ):
        """
         Read the configurations from the remote device and print it out.

         Args:
             motor:
             config_type: Either a ServoConfig or StepperConfig class reference
             timeout: Duration before failure
         """
        t_perf_end = time.perf_counter() + timeout
        while True:
            if self.request_motor_config(motor):
                config = self.get_response(config_type, target_of_motor(motor),
                                           motor=motor, timeout=0.1)
                if config is not None:
                    self.set_motor_configuration(motor, config, write_to_remote=False)
                    logger.info("Pulled configuration for %s", motor)
                    break
                logger.error("Failed to get configuration for %s", motor)
            else:
                logger.error("Failed to request motor configuration for %s", motor)
                time.sleep(0.01)
            if time.perf_counter() > t_perf_end:
                raise RuntimeError(f"Could not get config for motor {motor} in time")

    def _query_configuration(self):
        """
        Query all motor configurations from the remote devices
        """
        self._query_motor_configuration(Motor.PELLET_X_MOTOR, StepperConfig)
        self._query_motor_configuration(Motor.PELLET_Y_MOTOR, StepperConfig)
        self._query_motor_configuration(Motor.PELLET_Z_MOTOR, StepperConfig)
        self._query_motor_configuration(Motor.PELLET_LOAD_SERVO, ServoConfig)
        self._query_motor_configuration(Motor.PELLET_COVER_SERVO, ServoConfig)
        self._query_motor_configuration(Motor.TUNNEL_MAGNET_SERVO, ServoConfig)
        self._query_motor_configuration(Motor.TUNNEL_GATE_SERVO, ServoConfig)

    def delay(self, delay_sec) -> bool:
        """
        Issue a commanded delay at the target

        Args:
            delay_sec: Delay (seconds)

        Returns:
            bool: True if successful else False
        """
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            logger.error("PELLET_DEVICE addr None")
            return False
        uuid = CanInterface.next_uuid()
        res = self._jc.Delay(addr, int(delay_sec * 1000), uuid)
        logger.debug("Delay addr=%s res=%s uuid=%s", addr, res, uuid)
        return res == 0

    def tare_load_cell(self) -> bool:
        """
        Tare the load cell so the current reading is 0.

        Returns:
            bool: True if successful else False
        """
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        if addr is None:
            logger.error("MAGNET_DEVICE addr None")
            return False
        uuid = self.next_uuid()
        res = self._jc.LoadCellTare(addr, 0, uuid)
        logger.debug("LoadCellTare addr=%s res=%s uuid=%s", addr, res, uuid)
        return res == 0

    def _move_servo_motor(self, motor: Motor, position, config: ServoConfig):
        """
        Move a servo motor.

        Args:
            motor
            position: Either a position (float) or a (position, rate (%)) pair
            config: associated motor configuration

        Returns:
            bool: True if successful else False
        """

        if isinstance(position, float) or isinstance(position, int):
            velocity = config.maximum_velocity
        elif isinstance(position, tuple):
            velocity = float(position[1]) / 100.0 * config.maximum_velocity
            position = float(position[0])
        else:
            logger.warning("unhandled pos: %s", position)
            return False

        prev_pos = position
        if position < 0:
            position = 0
        elif position > 180:
            position = 180
        if prev_pos != position:
            logger.verbose("Limiting servo %s move from %.1f to %.1f", motor, prev_pos, position)

        acceleration = config.maximum_acceleration

        addr = self._tgt2addr(target_of_motor(motor))
        if addr is None:
            logger.warning("no addr for motor-servo=%s", motor)
            return False
        uuid = CanInterface.next_uuid()
        res = self._jc.ServoMove(addr, _motor_to_id(motor),
                                                       position,
                                                       velocity,
                                                       acceleration,
                                                       AbsOrRel.ABSOLUTE,
                                                       uuid)
        logger.debug("%s: servo move %.3f mm with v=%.3f mm/s**2 ; res=%s uuid=%s ; config=%s",
                     motor, position, velocity, res, uuid, config)
        return res == 0

    def _move_stepper_motor(
        self,
        motor: Motor,
        position: Union[float, Tuple[float, float]],
        config: StepperConfig,
        save_as_fixed: bool,
        relative: bool = False,
    ):
        """
        Move a stepper motor.
        
        Args:
            motor
            position: Either a position (float) or a (position, rate (%)) pair
            config: associated motor configuration
            save_as_fixed: To save the passed position as fixed.
            relative: Relative movement or absolute, default absolute.

        Returns:
            bool: True if successful else False
        """
        addr = self._tgt2addr(target_of_motor(motor))
        if addr is None:
            logger.error("%s: target addr is None", motor)
            return False

        if isinstance(position, (float, int)):
            velocity = config.maximum_velocity
        elif isinstance(position, tuple) and len(position) == 2:
            velocity = float(position[1]) / 100.0 * config.maximum_velocity
            position = float(position[0])
        else:
            logger.error("Unhandled position type: %s ; value=%r", type(position), position)
            return False

        motor_axis_idx = _motor_to_axis_idx(motor)
        axis_prev_send_pos = self._prev_send_pos[motor_axis_idx]
        char_coord = "xyz"[motor_axis_idx]

        if save_as_fixed:
            if relative:
                # force absolute for save_as_fixed position,
                # this allows to only account 1 time for the possible auto-corrected drift
                relative = False
                position += axis_prev_send_pos
            self._prev_send_pos = self._prev_send_pos.replace(**{char_coord: position})

        corrected_position = position
        if save_as_fixed and self._auto_correct_motor_drift:
            axis_drift = self._motors_drift[motor_axis_idx]
            self._active_motors_drift = self._active_motors_drift.replace(**{char_coord: axis_drift})
            corrected_position = position - axis_drift
            # logger.debug("%s: corrected %.3f -> %.3f", motor, position, corrected_position)

        logger.verbose("%s: %s %s %.3f mm (corrected %.3f) with v=%.3f mm/s**2",
                     motor,
                       ("move", "save_as_fixed")[save_as_fixed],
                       ("absolute", "relative")[relative],
                       position, corrected_position, velocity)

        turns_position = mm_to_turns(corrected_position)
        turns_velocity = mm_to_turns(velocity)
        turns_acceleration = mm_to_turns(config.maximum_acceleration)

        if relative:
            if not save_as_fixed and motor in self._last_positions:
                last_pos = self._last_positions[motor]
                if last_pos is None:
                    logger.error("Motor %s: refusing relative movement with no last_pos known", motor)
                    return False
                tentative = last_pos + position
                if tentative < 0:
                    position -= tentative
                    turns_position = mm_to_turns(position)
                    logger.verbose("Limiting relative move to %s", position)
                elif tentative > _STEPPER_MAX_POS:
                    position = _STEPPER_MAX_POS - last_pos
                    turns_position = mm_to_turns(position)
                    logger.verbose("Limiting relative move to %s", position)
                # force set our last receive position:
                self._last_positions[motor] += position
                # so that multiple consecutive relative movement (without having received a stepper status in between),
                # won't make the checks to be missed.
        else:
            # absolute move
            if turns_position < 0:
                logger.debug("limited turns_position to 0 ; was %.1f", turns_position)
                turns_position = 0
            elif turns_position > _STEPPER_MAX_TURNS:
                logger.debug("limited turns_position to max ; was %.1f", turns_position)
                turns_position = _STEPPER_MAX_TURNS

        uuid = CanInterface.next_uuid()
        res = self._jc.StepperMove(
            addr,
            _motor_to_id(motor),
            turns_position,
            turns_velocity,
            turns_acceleration,
            AbsOrRel.RELATIVE if relative else AbsOrRel.ABSOLUTE,
            save_as_fixed,
            uuid,
        )
        logger.debug("%s: StepperMove res=%s uuid=%s", motor, res, uuid)
        return res == 0

    def move_magnet_servo(self, position) -> bool:
        """
        Move the magnet motor

        Args:
            position: Either a position (float) or a (position, rate (%)) pair

        Returns:
            bool: True if successful else False
        """
        return self._move_servo_motor(Motor.TUNNEL_MAGNET_SERVO, position, self.magnet_config)

    def move_gate_servo(self, position) -> bool:
        """
        Move the gate motor

        Args:
            position: Either a position (float) or a (position, rate (%)) pair

        Returns:
            bool: True if successful else False
        """
        return self._move_servo_motor(Motor.TUNNEL_GATE_SERVO, position, self.gate_config)

    def set_motor_x(self, position: float, *, relative: bool = False) -> bool:
        # NB: SET == saved-as-fixed:
        return self.move_motor_x(position, save_as_fixed=True, relative=relative)

    def move_motor(self, motor: Motor, position, *, save_as_fixed: bool = False, relative: bool = False):
        # unused
        # only for steppers, XYZ
        return self._move_stepper_motor(
            motor, position, self._motor_configs[motor],
            save_as_fixed=save_as_fixed, relative=relative,
        )

    def move_motor_x(
        self,
        position: Union[float, Tuple[float, float]],
        save_as_fixed: bool = False,
        *,
        relative: bool = False,
    ) -> bool:
        """
         Move the X-direction motor

        Args:
            position: Either a position (float) or a (position, rate (%)) pair
            save_as_fixed: Save the position as a new fixed location for this motor
                If True then the position is only saved-as-fixed, the motor is not moved.
            relative: Relative movement or absolute, default absolute.

         Returns:
             bool: True if successful else False
         """
        return self._move_stepper_motor(Motor.PELLET_X_MOTOR, position, self.x_config,
                                        save_as_fixed=save_as_fixed, relative=relative)

    def set_motor_y(self, position, *, relative: bool = False) -> bool:
        return self.move_motor_y(position, save_as_fixed=True, relative=relative)

    def move_motor_y(self, position, save_as_fixed: bool = False, *, relative: bool = False) -> bool:
        """
         Move the Y-direction motor

         Args:
             position: Either a position (float) or a (position, rate (%)) pair
             save_as_fixed: Save the position as a new fixed location for this motor
                If True then the position is only saved-as-fixed, the motor is not moved.
             relative: Relative movement or absolute, default absolute.

         Returns:
             bool: True if successful else False
         """
        return self._move_stepper_motor(Motor.PELLET_Y_MOTOR, position, self.y_config,
                                        save_as_fixed=save_as_fixed, relative=relative)

    def set_motor_z(self, position, *, relative: bool = False) -> bool:
        return self.move_motor_z(position, save_as_fixed=True, relative=relative)

    def move_motor_z(self, position, save_as_fixed: bool = False, *, relative: bool = False) -> bool:
        """
         Move the Z-direction motor

         Args:
             position: Either a position (float) or a (position, rate (%)) pair
             save_as_fixed: Save the position as a new fixed location for this motor
                If True then the position is only saved-as-fixed, the motor is not moved.
             relative: Relative movement or absolute, default absolute.

         Returns:
             bool: True if successful else False
         """
        return self._move_stepper_motor(Motor.PELLET_Z_MOTOR, position, self.z_config,
                                        save_as_fixed=save_as_fixed, relative=relative)

    def fixed_position(self) -> bool:
        """
        Move the X, Y, Z motor to a fixed location, known by the device

        Returns:
            bool: True if successful else False
        """
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            return False
        uuid = CanInterface.next_uuid()
        res = self._jc.SendToFixedXYZ(addr, uuid)
        logger.debug("SendToFixedXYZ res=%s uuid=%s", res, uuid)
        return res == 0

    def move_load_servo(self, position):
        """
        Move the load arm

        Args:
            position: Either a position (float) or a (position, rate (%)) pair

        Returns:
            bool: True if successful else False
        """
        return self._move_servo_motor(Motor.PELLET_LOAD_SERVO, position, self.load_config)

    def scoop_pellet(self) -> bool:
        """
        Move to scoop a pellet

        Returns:
            bool: True if successful else False
        """
        return self.move_load_servo(self.load_config.minimum_position)

    def retrieve_pellet(self) -> bool:
        """
        Move to retrieve a pellet

            Returns:
                bool: True if successful else False
        """
        return self.move_load_servo(self.load_config.maximum_position)

    def move_cover_servo(self, position):
        """
        Move the cover servo

        Args:
            position: Either a position (float) or a (position, rate (%)) pair

        Returns:
            bool: True if successful else False
        """
        return self._move_servo_motor(Motor.PELLET_COVER_SERVO, position, self.cover_config)

    def release_pellet(self) -> bool:
        """
        Open the cover so the pellet is visible to the animal

        Returns:
            bool: True if successful else False
        """
        return self.move_cover_servo(self.cover_config.minimum_position)

    def cover_pellet(self) -> bool:
        """
        Close the cover so the pellet is not visible to the animal

        Returns:
            bool: True if successful else False
        """
        return self.move_cover_servo(self.cover_config.maximum_position)

    def stepper_home(self, motor: Motor) -> bool:
        """
        Send the given motor (X, Y, or Z) to the 0 position

        Args:
            motor:

        Returns:
            bool: True if successful else False
        """
        logger.info(f"Homing Stepper Motor {motor_to_str(motor)}")
        if is_servo(motor):
            logger.warning("invalid stepper home motor: %s", motor)
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            logger.warning("No pellet device addr found")
            return False
        # Third arg - forward/rev. Go in forward direction if the non-zero locations are negative
        uuid = CanInterface.next_uuid()
        res = self._jc.StepperHome(addr, _motor_to_id(motor), uuid)
        logger.debug("%s StepperHome res=%s uuid=%s", motor, res, uuid)
        return res == 0

    def _write_stepper_config(self, config: StepperConfig) -> bool:
        """
        Update a stepper motor configuration on the target

`       Args:
            config: Configuration to update

        Returns:
            bool: True if successful else False
        """
        motor_id = _motor_to_id(config.motor)
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            logger.error("No address for target %s for motor %s", Target.PELLET_DEVICE, config.motor)
            return False

        max_vel = mm_to_turns(config.maximum_velocity)
        max_acc = mm_to_turns(config.maximum_acceleration)
        home_vel = mm_to_turns(config.homing_velocity)

        uuid = CanInterface.next_uuid()
        res = self._jc.StepperCfgWrite(addr, motor_id,
                                    config.microsteps,
                                    config.steps_per_revolution,
                                    max_vel,
                                    max_acc,
                                    home_vel,
                                    config.flip_limit_orientation,
                                    uuid)
        logger.debug("StepperCfgWrite addr=%s config=%s: res=%s uuid=%s",
                     addr, config, res, uuid)
        if res != 0:
            logger.error(
                "stepper %s addr=%s config write failed", config.motor, addr)
            return False
        return True

    def _write_servo_config(self, config: ServoConfig) -> bool:
        """
        Update a servo motor configuration on the target

        Args:
            config: Configuration to update

        Returns:
            bool: True if successful else False
        """
        motor_id = _motor_to_id(config.motor)
        target = target_of_motor(config.motor)

        addr = self._tgt2addr(target)
        if addr is None:
            logger.error("No address for target %s for motor %s", target, config.motor)
            return False

        uuid = CanInterface.next_uuid()
        res = self._jc.ServoCfgWrite(addr, motor_id,
                                  config.minimum_position,
                                  config.maximum_position,
                                  config.minimum_pwm_duration,
                                  config.maximum_pwm_duration,
                                  config.maximum_velocity,
                                  config.maximum_acceleration,
                                  uuid)
        logger.debug("ServoCfgWrite addr=%s config=%s: res=%s uuid=%s", addr, config, res, uuid)
        if res != 0:
            logger.error("servo %s %s config write failed", addr, motor_id)
            return False
        return True

    def request_motor_config(self, motor: Motor) -> bool:
        """
        Request a stepper motor configuration from a target

        Args:
            motor:

        Returns:
            bool: True if successful else False
        """
        target = target_of_motor(motor)
        msg = JerryCANCfgMsg()
        if is_servo(motor):
            msg.type = JerryCANCfgMsg.Type.SERVO
            msg.servo.motor_id = _motor_to_id(motor)
        else:
            msg.type = JerryCANCfgMsg.Type.STEPPER
            msg.stepper.motor_id = _motor_to_id(motor)

        addr = self._tgt2addr(target)
        if addr is None:
            logger.warning("tgt2addr None for motor=%s target=%s", motor, target)
            return False
        res = self._jc.CfgRead(addr, msg)
        logger.debug("motor=%s: tentative request addr=%s tgt=%s => res=%s", motor, addr, target, res)
        return res == 0

    def send_heartbeat(self) -> bool:
        """
        Send a heartbeat message to the target; causes an LED to blink briefly.

        Returns:
            bool: True if successful else False
        """
        return self._jc.Heartbeat() == 0

    def set_digital_output(self, gpio: DigitalOutputs, state: bool) -> bool:
        """
        Set a digital output value on the pellet device

        Args:
            gpio: Digital output to change
            state: On (True) or Off (False) state

         Returns:
             bool: True if successful else False
         """

        # These values are based on the order and listing in the DTS files for
        # each board.
        if gpio == DigitalOutputs.STIMULUS_1:
            gpio_id = 4
        elif gpio == DigitalOutputs.STIMULUS_2:
            gpio_id = 5
        elif gpio == DigitalOutputs.STIMULUS_3:
            gpio_id = 6
        elif gpio == DigitalOutputs.STIMULUS_4:
            gpio_id = 7
        else:
            logger.warning("Unhandled digital output: %s", gpio)
            return True

        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            return False
        uuid = CanInterface.next_uuid()
        res = self._jc.GPIOWrite(addr, 0, gpio_id, state, uuid)
        logger.debug("set_digital_output addr=%s gpio_id=%s state=%s res=%s uuid=%s",
                     addr, gpio_id, state, res, uuid)
        return res == 0

    def emit_tone(self, frequency: int, duration_ms: int) -> bool:
        """
        Emit a tone for the animal to hear

        Args:
            frequency: Frequency of tone (Hz)
            duration_ms: Duration of tone (milliseconds)

        Returns:
            bool: True if successful else False
        """
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            return False
        uuid = CanInterface.next_uuid()
        res = self._jc.ToneWrite(addr, 0, frequency, duration_ms, uuid)
        logger.debug("emit_tone addr=%s freq=%s duration_ms=%s res=%s uuid=%s",
                     addr, frequency, duration_ms, res, uuid)
        return res == 0

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        """
        Set an analog output on the pellet device

        Args:
            channel: Channel #
            millivolts: desired voltage output (millivolts)

        Returns:
            bool: True if successful else False
        """
        if channel == AnalogOutputs.STATUS_OUT:
            channel = 0
        else:
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.AnalogOutWrite(addr,
                                                            channel,
                                                            millivolts,
                                                            CanInterface.next_uuid()) == 0

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        """
        Set the colors of a 3-color LED.

        Args:
            red_percent: % in red
            green_percent: % in green
            blue_percent: % in blue

        Returns:
            bool: True if successful else False
        """
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.RGBLEDWrite(addr,
                                                         red_percent,
                                                         green_percent,
                                                         blue_percent,
                                                         CanInterface.next_uuid()) == 0

    def request_version(self) -> bool:
        """
        Request the versions of the pellet and magnet board firmware

        Returns:
            bool: True if successful else False
        """
        pellet = self._tgt2addr(Target.PELLET_DEVICE)
        magnet = self._tgt2addr(Target.MAGNET_DEVICE)
        if pellet is None or magnet is None:
            logger.error("Cannot request version: pellet addr=%s magnet addr=%s", pellet, magnet)
            return False
        rc = self._jc.BootloaderCommand(pellet,
                                        JerryCANBootloaderCmd.SubCommand.VERSION)
        if rc == 0:
             rc = self._jc.BootloaderCommand(magnet,
                                             JerryCANBootloaderCmd.SubCommand.VERSION)
        return rc == 0

    # NOTE: E-Stop is not implemented in the target
    # def emergency_stop(self) -> bool:
    #  return self.is_open and self._jc.EStop() == 0

    @staticmethod
    def _assign_timestamp_ns(message):
        return time.time_ns()

    def _translate(self, message) -> Optional[Any]:
        """
        Translate from a JerryCANCmd class to a class specific to the data type received

        Args:
            message: jerrycan_msg_t type; interpret using message.type

        Returns:
            Populated class type (see device_interface.py) or None
        """
        handler = self._handlers.get(message.type, None)
        if handler is None:
            logger.warning("Unhandled message type: %s", message.type)
            return None
        res = handler(message)
        if res is not None:
            assert isinstance(res, Source)
            res.timestamp_ns = self._get_timestamp_ns(message)
            res.index = self._get_index(message)
        return res

    @staticmethod
    def _translate_bootloader(message) -> Optional[Version]:
        """
        Translate bootloader response messages.

        Args:
            message: JerryCANMsg with bootloader response data

        Returns:
            Version object if the bootloader response is a version request, None otherwise
        """
        if message.bootloader_response.type == JerryCANBootloaderCmd.SubCommand.VERSION:
            target = _addr2tgt(message.dst_id)
            if hasattr(message.bootloader_response.version, "running_major"):
                # pyjerrycan < 1.2.0
                version_str = f"{target_to_str(target)}: {message.bootloader_response.version.running_major}." \
                              f"{message.bootloader_response.version.running_minor}." \
                              f"{message.bootloader_response.version.running_patch}"
            else:
                # pyjerrycan >= 1.2.0
                version_str = f"{target_to_str(target)}: {message.bootloader_response.version.running_version_major}." \
                              f"{message.bootloader_response.version.running_version_minor}." \
                              f"{message.bootloader_response.version.running_version_patch}"
            return Version(target, version=version_str)
        return None

    def _translate_config(self, message) -> \
        Optional[Union[ServoConfig, StepperConfig]]:
        """
        Translate configuration response messages for servo or stepper motors.

        Args:
            message: JerryCANMsg with configuration data

        Returns:
            ServoConfig or StepperConfig object depending on the message type
        """
        if message.cfg_response.type == JerryCANCfgMsg.Type.SERVO:
            return self._translate_servo_config(message)
        elif message.cfg_response.type == JerryCANCfgMsg.Type.STEPPER:
            return self._translate_stepper_config(message)
        logger.warning("Unknown config type: %s", message.cfg_response.type)
        return None

    def _translate_servo_config(self, message) -> ServoConfig:
        """
        Translate servo configuration response messages.

        Args:
            message: JerryCANMsg with servo configuration data

        Returns:
            ServoConfig object with updated settings
        """
        target = _addr2tgt(message.dst_id)
        motor = _id_to_motor(target, True, message.cfg_response.servo.motor_id)

        config = self.get_motor_configuration(motor)

        # Update configuration with values from the message
        config.minimum_position = message.cfg_response.servo.min_position
        config.maximum_position = message.cfg_response.servo.max_position
        config.minimum_pwm_duration = message.cfg_response.servo.min_pwm_duration_us
        config.maximum_pwm_duration = message.cfg_response.servo.max_pwm_duration_us
        config.maximum_velocity = message.cfg_response.servo.motor_max_velocity
        config.maximum_acceleration = message.cfg_response.servo.motor_max_acceleration

        return config

    def _translate_stepper_config(self, message) -> StepperConfig:
        """
        Translate stepper configuration response messages.

        Args:
            message: JerryCANMsg with stepper configuration data

        Returns:
            StepperConfig object with updated settings
        """
        target = _addr2tgt(message.dst_id)
        motor = _id_to_motor(target, False, message.cfg_response.stepper.motor_id)

        config = self.get_motor_configuration(motor)

        # Update configuration with values from the message
        config.microsteps = message.cfg_response.stepper.microsteps
        config.steps_per_revolution = message.cfg_response.stepper.steps_per_revolution
        config.flip_limit_orientation = message.cfg_response.stepper.flip_limit_orientation
        config.maximum_velocity = turns_to_mm(message.cfg_response.stepper.motor_max_velocity)
        config.maximum_acceleration = turns_to_mm(
            message.cfg_response.stepper.motor_max_acceleration)
        config.homing_velocity = turns_to_mm(message.cfg_response.stepper.homing_velocity)

        return config

    @staticmethod
    def _translate_gpio(message) -> Union[MagnetDigitalInputs, PelletDigitalInputs]:
        """
        Translate GPIO read response messages.

        Args:
            message: JerryCANMsg with GPIO state data

        Returns:
            MagnetDigitalInputs or PelletDigitalInputs depending on the source address
        """
        if _is_magnet_by_addr(message.dst_id):
            gpios = MagnetDigitalInputs()
            gpios.target = _addr2tgt(message.dst_id)
            gpios.continuity_0 = bool(message.gpio_read.state & 0x10)
            gpios.continuity_1 = bool(message.gpio_read.state & 0x20)
            return gpios
        else:
            gpios = PelletDigitalInputs()
            gpios.target = _addr2tgt(message.dst_id)
            gpios.stimulus_1 = message.gpio_read.state & 0x010 == 0x010
            gpios.stimulus_2 = message.gpio_read.state & 0x020 == 0x020
            gpios.stimulus_3 = message.gpio_read.state & 0x040 == 0x040
            gpios.stimulus_4 = message.gpio_read.state & 0x080 == 0x080
            return gpios

    @staticmethod
    def _translate_analog_out(message) -> Optional[AnalogOutput]:
        """
        Translate analog output response messages.

        Args:
            message: JerryCANMsg with analog output data

        Returns:
            AnalogOutput object if it's from the pellet device, None otherwise
        """
        if message.analog_out.instance == 0 and _is_pellet_by_addr(message.dst_id):
            analog = AnalogOutput()
            analog.target = _addr2tgt(message.dst_id)
            analog.status_out_mv = message.analog_out.value_mv
            return analog
        return None

    def _handle_audio_begin(self, message) -> None:
        """
        Handle the beginning of audio magnitude data stream.
        This method updates internal state but doesn't return data.

        Args:
            message: JerryCANMsg with beginning of audio data
        """
        self._audio.magnitudes.clear()
        self._audio.target = _addr2tgt(message.dst_id)
        self._audio.packet_id = message.audio_data_cmd.stream_id
        # NB: kind of duplicate:
        self._audio.when = self._get_timestamp_ns(message) / 1e9
        # when : timestamp_ns is already applied in self._translate() method
        # But really duplicate:
        # self._audio.index = self._get_index(message)
        # index now already applied in self._translate() too
        return None

    def _handle_audio_cont(self, message) -> None:
        """
        Handle continuation of audio magnitude data stream.
        This method updates internal state but doesn't return data.

        Args:
            message: JerryCANMsg with continued audio data
        """
        cur_audio = self._audio
        if cur_audio.packet_id != 0 and cur_audio.target == _addr2tgt(message.dst_id):
            cur_audio.magnitudes.extend(message.audio_data.magnitudes)
        else:
            logger.warning("Unknown audio cont: target=%s cur=%s magnitudes=%s",
                           _addr2tgt(message.dst_id), cur_audio.target, message.audio_data.magnitudes)
        return None

    def _handle_audio_end(self, message) -> Optional[AudioData]:
        """
        Handle the end of audio magnitude data stream.

        Args:
            message: JerryCANMsg with end of audio data marker

        Returns:
            AudioData object if a complete packet was received, None otherwise
        """

        cur_audio = self._audio
        if message.audio_data_cmd.stream_id == cur_audio.packet_id:
            if len(cur_audio.magnitudes) != 64:
                logger.debug("missing or unexpected extra audio data, got %s, awaited 64 ; data skipped",
                             len(cur_audio.magnitudes))
                a = None
            else:
                # todo: could use copy.deepcopy for faster creation probably:
                a = AudioData(
                    target=cur_audio.target,
                    when=cur_audio.when,
                    index=cur_audio.index,
                    magnitudes=cur_audio.magnitudes,
                    packet_id=cur_audio.packet_id,
                )
        else:
            logger.warning("Got unknown or unexpected audio end: packet_id=%s cur=%s",
                           message.audio_data_cmd.stream_id, cur_audio.packet_id)
            a = None

        # Reset the audio buffer state
        cur_audio.magnitudes = []
        cur_audio.packet_id = 0

        return a

    @staticmethod
    def _translate_door_sensor(message) -> DoorData:
        """
        Translate door sensor response messages.

        Args:
            message: JerryCANMsg with door sensor data

        Returns:
            DoorData object with state information
        """
        door = DoorData()
        door.target = _addr2tgt(message.dst_id)

        # Reported state is inverse of requested state
        door.door1 = message.doors.door1
        door.door2 = message.doors.door2
        door.door3 = message.doors.door3
        door.ext_button = message.doors.ext_button

        return door

    @staticmethod
    def _translate_servo_status(message) -> Optional[ServoStatus]:
        """
        Translate servo status response messages.

        Args:
            message: JerryCANMsg with servo status data

        Returns:
            ServoStatus object if the motor is recognized, None otherwise
        """
        target = _addr2tgt(message.dst_id)
        motor = _id_to_motor(target, True, message.servo_status.motor_id)

        if motor == Motor.NONE:
            return None

        return ServoStatus(target, motor, message.servo_status.position)

    def _handle_stepper_status(self, message):
        status = self._translate_stepper_status(message)
        if status is None:
            return None
        if status.motor in self._last_positions:
            self._last_positions[status.motor] = status.position
        return status

    def _translate_stepper_status(self, message) -> Optional[StepperStatus]:
        """
        Translate stepper status response messages.

        Args:
            message: JerryCANMsg with stepper status data

        Returns:
            StepperStatus object if the motor is recognized, None otherwise
        """
        target = _addr2tgt(message.dst_id)
        motor = _id_to_motor(target, False, message.stepper_status.motor_id)
        if motor == Motor.NONE:
            logger.warning("_translate_stepper_status: target=%s motor=%s dst_id=%s motor_id=%s",
                           target, motor, message.dst_id, message.stepper_status.motor_id)
            return None
        motor_axis_idx = _motor_to_axis_idx(motor)
        motor_send_pos = turns_to_mm(message.stepper_status.send_position)
        if self._auto_correct_motor_drift:
            motor_send_pos += self._active_motors_drift[motor_axis_idx]
        status = StepperStatus(
            target=target,
            motor=motor,
            position=turns_to_mm(message.stepper_status.position),
            send_position=motor_send_pos,
            limit_switch=message.stepper_status.limit_switch == 1,
            position_error=self._motors_drift_error[motor_axis_idx],
        )
        return status

    def servo_attach(self, motor: Motor):
        addr = self._tgt2addr(target_of_motor(motor))
        motor_id = _motor_to_id(motor)
        res = self._jc.ServoAttach(addr, motor_id)
        if res != 0:
            logger.error("%s: ServoAttach failed: %s", motor, res)
        return res == 0

    def servo_detach(self, motor: Motor):
        addr = self._tgt2addr(target_of_motor(motor))
        motor_id = _motor_to_id(motor)
        res = self._jc.ServoDetach(addr, motor_id)
        if res != 0:
            logger.error("%s: ServoDetach failed: %s", motor, res)
        return res == 0
