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
import time

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, AbsOrRel, \
        JerryCANBootloaderCmd

except (ModuleNotFoundError, TypeError, AttributeError):
    pass

from .device_interface import *
from .stepper_motor import mm_to_turns, turns_to_mm
from autotrainer.core.message import Motor

logger = logging.getLogger(__name__)

_MAGNET_SERVO_ID = 0

_PELLET_X_MOTOR_ID = 0
_PELLET_Y_MOTOR_ID = 1
_PELLET_Z_MOTOR_ID = 2

_PELLET_COVER_SERVO_ID = 0
_PELLET_LOAD_SERVO_ID = 1

_audio = AudioData()

"""
Pellet device CAN address board type is 0 (bits 2 and 3)
"""


def _is_pellet_by_addr(addr: int) -> bool:
    return addr & 0xC == 0


"""
Pellet device CAN address board type is 4 (bits 2 and 3)
"""


def _is_magnet_by_addr(addr: int) -> bool:
    return addr & 0xC == 0x04


"""
Convert a CANbus address to a target type
"""


def _addr2tgt(addr: int) -> Target:
    return Target.PELLET_DEVICE if _is_pellet_by_addr(addr) else Target.MAGNET_DEVICE


"""
Given a target type, return an equivalent human-readable string
"""


def target_to_str(target: Target) -> str:
    if target is Target.PELLET_DEVICE:
        return "Pellet"
    elif target is Target.MAGNET_DEVICE:
        return "Magnet"
    else:
        return "Unknown"


"""
Given a motor type, return an equivalent human-readable string
"""


def motor_to_str(motor: Motor) -> str:
    if motor is Motor.PELLET_X_MOTOR:
        return "X"
    elif motor is Motor.PELLET_Y_MOTOR:
        return "Y"
    elif motor is Motor.PELLET_Z_MOTOR:
        return "Z"
    elif motor is Motor.MAGNET_SERVO:
        return "Magnet"
    elif motor is Motor.PELLET_LOAD_SERVO:
        return "Load"
    elif motor is Motor.PELLET_COVER_SERVO:
        return "Cover"
    else:
        return "Unknown"


"""
Given a motor type, return the Alagus hardware motor identification number
"""


def _motor_to_id(motor: Motor) -> int:
    if motor is Motor.PELLET_X_MOTOR:
        return _PELLET_X_MOTOR_ID
    elif motor is Motor.PELLET_Y_MOTOR:
        return _PELLET_Y_MOTOR_ID
    elif motor is Motor.PELLET_Z_MOTOR:
        return _PELLET_Z_MOTOR_ID
    elif motor is Motor.MAGNET_SERVO:
        return _MAGNET_SERVO_ID
    elif motor is Motor.PELLET_LOAD_SERVO:
        return _PELLET_LOAD_SERVO_ID
    elif motor is Motor.PELLET_COVER_SERVO:
        return _PELLET_COVER_SERVO_ID

    return 0


"""
Return - Indication if the motor is a servo motor type
"""


def is_servo(motor: Motor) -> bool:
    return motor is Motor.MAGNET_SERVO or \
        motor is Motor.PELLET_LOAD_SERVO or \
        motor is Motor.PELLET_COVER_SERVO


"""
Return - Indication if the motor is a stepper motor type
"""


def is_stepper(motor: Motor) -> bool:
    return not is_servo(motor)


"""
Return - Given the motor, determines which physical board the motor is associated with
"""


def target_of_motor(motor: Motor) -> Target:
    return Target.MAGNET_DEVICE if motor is Motor.MAGNET_SERVO else Target.PELLET_DEVICE


"""
Given a Alagus hardware motor identification number and target, return the motor type
"""


def _id_to_motor(target: Target, isa_servo: bool, motor_id: int) -> Motor:
    if target is Target.MAGNET_DEVICE:
        if isa_servo:
            if motor_id is _MAGNET_SERVO_ID:
                return Motor.MAGNET_SERVO
    else:
        if isa_servo:
            if motor_id is _PELLET_COVER_SERVO_ID:
                return Motor.PELLET_COVER_SERVO
            elif motor_id is _PELLET_LOAD_SERVO_ID:
                return Motor.PELLET_LOAD_SERVO
        else:
            if motor_id is _PELLET_X_MOTOR_ID:
                return Motor.PELLET_X_MOTOR
            elif motor_id is _PELLET_Y_MOTOR_ID:
                return Motor.PELLET_Y_MOTOR
            elif motor_id is _PELLET_Z_MOTOR_ID:
                return Motor.PELLET_Z_MOTOR

    return Motor.NONE


class CanInterface(DeviceInterface):
    """
    CanInterface implements the details of
        * communication (read and write) with Alogus hardware interface (pyjerrcan)

    Applications and scripts would generally not interact with this class directly,
    but with the more generalized behavior in the CanDevice class.
    """

    _uuid: int = 1

    @classmethod
    def next_uuid(cls) -> int:
        cls._uuid = cls._uuid + 1 & 0xFF
        if cls._uuid == 0:  # don't allow 0's
            cls._uuid = 1
        return cls._uuid

    @classmethod
    def uuid(cls) -> int:
        return cls._uuid

    def __init__(self):
        super().__init__()

        try:
            self._jc = JerryCAN()
        except (ModuleNotFoundError, TypeError, AttributeError):
            self._jc = None

        self._is_open = False

        self._pellet_addr: typing.Optional[int] = None
        self._magnet_addr: typing.Optional[int] = None

        self.magnet_config = ServoConfig()
        self.load_config = ServoConfig()
        self.cover_config = ServoConfig()
        self.x_config = StepperConfig()
        self.y_config = StepperConfig()
        self.z_config = StepperConfig()

    @property
    def magnet_config(self):
        return self._magnet_config

    @magnet_config.setter
    def magnet_config(self, config: ServoConfig):
        self._magnet_config = config if config is not None else ServoConfig()
        self._magnet_config.motor = Motor.MAGNET_SERVO
        self._magnet_config.target = target_of_motor(self._magnet_config.motor)

    @property
    def load_config(self):
        return self._load_config

    @load_config.setter
    def load_config(self, config: ServoConfig):
        self._load_config = config if config is not None else ServoConfig()
        self._load_config.motor = Motor.PELLET_LOAD_SERVO
        self._load_config.target = target_of_motor(self._load_config.motor)

    @property
    def cover_config(self):
        return self._cover_config

    @cover_config.setter
    def cover_config(self, config: ServoConfig):
        self._cover_config = config if config is not None else ServoConfig()
        self._cover_config.motor = Motor.PELLET_COVER_SERVO
        self._cover_config.target = target_of_motor(self._cover_config.motor)

    @property
    def x_config(self):
        return self._x_config

    @x_config.setter
    def x_config(self, config: StepperConfig):
        self._x_config = config if config is not None else StepperConfig()
        self._x_config.motor = Motor.PELLET_X_MOTOR
        self._x_config.target = target_of_motor(self._x_config.motor)

    @property
    def y_config(self):
        return self._y_config

    @y_config.setter
    def y_config(self, config: StepperConfig):
        self._y_config = config if config is not None else StepperConfig()
        self._y_config.motor = Motor.PELLET_Y_MOTOR
        self._y_config.target = target_of_motor(self._y_config.motor)

    @property
    def z_config(self):
        return self._z_config

    @z_config.setter
    def z_config(self, config: StepperConfig):
        self._z_config = config if config is not None else StepperConfig()
        self._z_config.motor = Motor.PELLET_Z_MOTOR
        self._z_config.target = target_of_motor(self._z_config.motor)

    """
    Set the pellet CAN address. Used primarily for testing, as after data is received
    from the device(s), the address for each target will be updated automatically.
    """

    def _set_pellet_address(self, addr: int):
        self._pellet_addr = addr
        logger.info(f"pellet module located at {self._pellet_addr}")

    """
    Set the magnet CAN address. Used primarily for testing, as after data is received
    from the device(s), the address for each target will be updated automatically.
    """

    def _set_magnet_address(self, addr: int):
        self._magnet_addr = addr
        logger.info(f"magnet module located at {self._magnet_addr}")

    """
    Determine if both the magnet and pellet CANbus addresses are valid
    """

    def are_addresses_valid(self) -> bool:
        return self._magnet_addr is not None and self._pellet_addr is not None

    """
    Return the CANbus address of the given target
    """

    def _tgt2addr(self, target: Target) -> int:
        dst = self._pellet_addr if target is Target.PELLET_DEVICE else self._magnet_addr
        return dst

    """
    Assign the pellet or magnet CANbus address based on an incoming message. Each
    target address is set only once.
    """

    def _assign_address(self, message):
        if self._pellet_addr is None and _is_pellet_by_addr(message.dst_id):
            self._set_pellet_address(message.dst_id)

        if self._magnet_addr is None and _is_magnet_by_addr(message.dst_id):
            self._set_magnet_address(message.dst_id)

    """
    Flag: interface to hardware is open (true) or closed (false)
    """

    @property
    def is_open(self) -> bool:
        return self._is_open

    """
    Open the interface (CANbus) connection
    """

    def open(self) -> bool:
        if self._jc is None:
            return False

        self._is_open = self._jc.Open() == 0

        self._query_configuration()

        return self._is_open

    """
    Close the interface (CANbus) connection
    """

    def close(self):
        if self._is_open:
            self._jc.Close()

    """
    Flag: Data can be read from the connection
    """

    def can_read(self) -> bool:
        return self._is_open

    """
    Read a set of packets from the CANbus.
    Returns a list of data classes (see device_interface.py for list of classes)
    """

    def read(self, max_count: int = 1) -> typing.Any:
        messages = []
        if self._is_open:
            while len(messages) < max_count:
                message = self._jc.ReceiveMessage()
                if message is None:
                    break
                else:
                    messages.append(message)
                    self._assign_address(message)

                # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
                # significantly slow down the system without explicitly yielding, despite being in its own thread.  This
                # is not the case for other platforms/combinations of the above so may not be apparent when not on the
                # deployment current platform.
                time.sleep(0.0001)

        return [x for x in map(self._translate, messages) if x is not None]

    """
    Do not allow the application to write unknown messages to the CANbus
    """

    def write(self, value: typing.Any) -> int:
        raise NotImplementedError()

    """
    Do not allow the application to write unknown messages to the CANbus
    """

    def write_str(self, value: str) -> int:
        raise NotImplementedError()

    """
    Read data until a specific response is detected
    """

    def get_response(self, typeof, target: Target, timeout: float = 2.0):
        now = time.time()

        while time.time() - now < timeout:
            messages = self.read(1)
            if len(messages) > 0:
                for msg in messages:
                    if isinstance(msg, typeof) and msg.target is target:
                        return msg
            time.sleep(0.001)

        return None

    """
    Return the configuration for the given motor
    """

    def get_motor_configuration(self, motor: Motor):
        if is_servo(motor):

            # Not all configuration items get pushed/pulled to the target
            # Reminder: config points to same object after assignment
            if motor is Motor.PELLET_COVER_SERVO:
                config = self.cover_config
            elif motor is Motor.PELLET_LOAD_SERVO:
                config = self.load_config
            elif motor is Motor.MAGNET_SERVO:
                config = self.magnet_config
            else:
                config = ServoConfig()
        else:
            if motor is Motor.PELLET_X_MOTOR:
                config = self.x_config
            elif motor is Motor.PELLET_Y_MOTOR:
                config = self.y_config
            elif motor is Motor.PELLET_Z_MOTOR:
                config = self.z_config
            else:
                config = StepperConfig()

        return config

    """
    Set a motor's configuration.
    
    motor - Motor associated with the configuration
    config - Configuration data
    write - Indication to push data to target (True), or locally store new configuration (False)
    """

    def set_motor_configuration(self, motor: Motor, config, write_to_remote: bool = True) -> bool:
        if config is None:
            return False

        rc = False

        config.motor = motor

        if motor is Motor.MAGNET_SERVO:
            self.magnet_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.magnet_config)

        elif motor is Motor.PELLET_X_MOTOR:
            self.x_config = config
            if write_to_remote:
                rc = self._write_stepper_config(self.x_config)

        elif motor is Motor.PELLET_Y_MOTOR:
            self.y_config = config
            if write_to_remote:
                rc = self._write_stepper_config(self.y_config)

        elif motor is Motor.PELLET_Z_MOTOR:
            self.z_config = config
            if write_to_remote:
                rc = self._write_stepper_config(self.z_config)

        elif motor is Motor.PELLET_COVER_SERVO:
            self.cover_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.cover_config)

        elif motor is Motor.PELLET_LOAD_SERVO:
            self.load_config = config
            if write_to_remote:
                rc = self._write_servo_config(self.load_config)

        return rc

    """
    Read the configurations from the remote device 
    """

    def _query_motor_configuration(self, motor: Motor, config_type):
        config = None
        while config is None:
            self.request_motor_config(motor)
            config = self.get_response(config_type, target_of_motor(motor), 2)
            if config is not None and config.motor == motor:
                self.set_motor_configuration(motor, config, False)
                logger.info(f"Pulled configuration for {motor_to_str(motor)}")
            else:
                logger.info(f"Failed to get configuration for {motor_to_str(motor)}")
                config = None

    def _query_configuration(self):
        self._query_motor_configuration(Motor.PELLET_X_MOTOR, StepperConfig)
        self._query_motor_configuration(Motor.PELLET_Y_MOTOR, StepperConfig)
        self._query_motor_configuration(Motor.PELLET_Z_MOTOR, StepperConfig)
        self._query_motor_configuration(Motor.PELLET_LOAD_SERVO, ServoConfig)
        self._query_motor_configuration(Motor.PELLET_COVER_SERVO, ServoConfig)
        self._query_motor_configuration(Motor.MAGNET_SERVO, ServoConfig)

    def delay(self, delay_sec) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and \
            self._jc.Delay(addr, int(delay_sec * 1000), CanInterface.next_uuid())

    def tare_load_cell(self) -> bool:
        """
        Tare the load cell so the current reading is 0.
        """
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.LoadCellTare(addr, 0, CanInterface.next_uuid()) == 0

    """
    Tare the pressure sensor so the current reading is 0.
    """

    def tare_pressure_sensor(self) -> bool:
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.PressureSensorTare(addr, 0, CanInterface.next_uuid()) \
            == 0

    def _set_servo_position(self, motor: Motor, position, config: ServoConfig):
        # The location is either a position or a (position, rate) pair

        if isinstance(position, float) or isinstance(position, int):
            velocity = config.maximum_velocity
        elif isinstance(position, tuple):
            velocity = float(position[1]) / 100.0 * config.maximum_velocity
            position = float(position[0])
        else:
            return

        if position < 0:
            position = 0
        elif position > 120:
            position = 120

        acceleration = config.maximum_acceleration

        addr = self._tgt2addr(target_of_motor(motor))
        return addr is not None and self._jc.ServoMove(addr, _motor_to_id(motor),
                                                       position,
                                                       velocity,
                                                       acceleration,
                                                       AbsOrRel.ABSOLUTE,
                                                       CanInterface.next_uuid()) == 0

    def _set_stepper_position(self, motor: Motor, position, config: StepperConfig, save_as_fixed:
    bool):
        # The location is either a position or a (position, rate) pair

        if isinstance(position, float) or isinstance(position, int):
            velocity = config.maximum_velocity
        elif isinstance(position, tuple):
            velocity = float(position[1]) / 100.0 * config.maximum_velocity
            position = float(position[0])
        else:
            return

        position = mm_to_turns(position)
        velocity = mm_to_turns(velocity)
        acceleration = mm_to_turns(config.maximum_acceleration)

        if position < 0:
            position = 0
        elif position > 12:
            position = 12

        addr = self._tgt2addr(target_of_motor(motor))
        return addr is not None and self._jc.StepperMove(addr, _motor_to_id(motor),
                                                         position,
                                                         velocity,
                                                         acceleration,
                                                         AbsOrRel.ABSOLUTE,
                                                         save_as_fixed,
                                                         CanInterface.next_uuid()) == 0

    """
    Set the position of the magnet motor
    """

    def set_magnet(self, position: int, _unused: bool = False) -> bool:
        return self._set_servo_position(Motor.MAGNET_SERVO, position, self.magnet_config)

    """
    Set the position of the X-direction motor
    """

    def set_x(self, position: float, save_as_fixed: bool = False) -> bool:
        return self._set_stepper_position(Motor.PELLET_X_MOTOR, position, self.x_config,
                                          save_as_fixed)

    """
    Set the position of the Y-direction motor
    """

    def set_y(self, position: float, save_as_fixed: bool = False) -> bool:
        return self._set_stepper_position(Motor.PELLET_Y_MOTOR, position, self.y_config,
                                          save_as_fixed)

    """
    Set the position of the Z-direction motor
    """

    def set_z(self, position: float, save_as_fixed: bool = False) -> bool:
        return self._set_stepper_position(Motor.PELLET_Z_MOTOR, position, self.z_config,
                                          save_as_fixed)

    """
    Move the X, Y, Z motor to a fixed location, known by the device
    """

    def fixed_position(self) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and \
            self._jc.SendToFixedXYZ(addr, CanInterface.next_uuid()) == 0

    """
    Set the position of the load arm
    """

    def set_load_servo(self, position: float, _unused: bool = False):
        return self._set_servo_position(Motor.PELLET_LOAD_SERVO, position, self.load_config)

    """
    Move to scoop a pellet
    """

    def scoop_pellet(self) -> bool:
        return self.set_load_servo(self.load_config.minimum_position)

    """
    Move to retrieve a pellet
    """

    def retrieve_pellet(self) -> bool:
        return self.set_load_servo(self.load_config.maximum_position)

    """
    Set the position of the cover for pellet delivery
    """

    def set_cover_servo(self, position, _unused: bool = False):
        return self._set_servo_position(Motor.PELLET_COVER_SERVO, position, self.cover_config)

    """
    Open the cover so the pellet is visible to the animal
    """

    def release_pellet(self) -> bool:
        return self.set_cover_servo(self.cover_config.minimum_position)

    """
    Open the cover so the pellet is visible to the animal
    """

    def cover_pellet(self) -> bool:
        return self.set_cover_servo(self.cover_config.maximum_position)

    """
    Send the given motor (X, Y, or Z) to the 0 position
    """

    def stepper_home(self, motor: Motor) -> bool:
        logger.info(f"Homing Stepper Motor {motor_to_str(motor)}")
        if is_servo(motor):
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)

        # Third arg - forward/rev. Go in forward direction if the non-zero locations are negative
        return addr is not None and self._jc.StepperHome(addr, _motor_to_id(motor),
                                                         CanInterface.next_uuid()) == 0

    """
    Update a stepper motor configuration on the target
    """

    def _write_stepper_config(self, config: StepperConfig) -> bool:
        motor_id = _motor_to_id(config.motor)
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            return False

        max_vel = mm_to_turns(config.maximum_velocity)
        max_acc = mm_to_turns(config.maximum_acceleration)

        if self._jc.StepperCfgWrite(addr, motor_id,
                                    config.microsteps,
                                    config.steps_per_revolution,
                                    max_vel,
                                    max_acc,
                                    config.flip_limit_orientation,
                                    CanInterface.next_uuid()) == 0:
            return True
        else:
            logger.error(
                f"stepper {addr} {motor_id} config write failed")
            return False

    """
    Update a servo motor configuration on the target
    """

    def _write_servo_config(self, config: ServoConfig) -> bool:
        motor_id = _motor_to_id(config.motor)
        target = target_of_motor(config.motor)

        addr = self._tgt2addr(target)
        if addr is None:
            return False

        if self._jc.ServoCfgWrite(addr, motor_id,
                                  config.minimum_position,
                                  config.maximum_position,
                                  config.minimum_pwm_duration,
                                  config.maximum_pwm_duration,
                                  config.maximum_velocity,
                                  config.maximum_acceleration,
                                  CanInterface.next_uuid()) == 0:
            return True
        else:
            logger.error(
                f"servo {addr} {motor_id} config write failed")
            return False

    """
    Request a stepper motor configuration from a target
    """

    def request_motor_config(self, motor: Motor) -> bool:
        target = target_of_motor(motor)
        msg = JerryCANCfgMsg()
        if is_servo(motor):
            msg.type = JerryCANCfgMsg.Type.SERVO
            msg.servo.motor_id = _motor_to_id(motor)
        else:
            msg.type = JerryCANCfgMsg.Type.STEPPER
            msg.stepper.motor_id = _motor_to_id(motor)

        addr = self._tgt2addr(target)
        return addr is not None and self._jc.CfgRead(addr, msg) == 0

    """
    Send a heartbeat message to the target; causes an LED to blink briefly.
    """

    def send_heartbeat(self) -> bool:
        return self._jc.Heartbeat() == 0

    """
    Set a digital output value on the pellet device
    """

    def set_digital_output(self, gpio: DigitalOutputs, state: bool) -> bool:
        # These values are based on the order and listing in the DTS files for
        # each board.
        if gpio is DigitalOutputs.STIMULUS_1:
            gpio_id = 4
        elif gpio is DigitalOutputs.STIMULUS_2:
            gpio_id = 5
        elif gpio is DigitalOutputs.STIMULUS_3:
            gpio_id = 6
        elif gpio is DigitalOutputs.STIMULUS_4:
            gpio_id = 7
        else:
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.GPIOWrite(addr, 0, gpio_id, state,
                                                       CanInterface.next_uuid()) == 0

    """
    Emit a tone for the animal to hear
    """

    def emit_tone(self, frequency: int, duration_ms: int) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ToneWrite(addr, 0,
                                                       frequency,
                                                       duration_ms,
                                                       CanInterface.next_uuid()) == 0

    """
    Set an analog output on the pellet device
    """

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        if channel is AnalogOutputs.STATUS_OUT:
            channel = 0
        else:
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.AnalogOutWrite(addr,
                                                            channel,
                                                            millivolts,
                                                            CanInterface.next_uuid()) == 0

    """
    Set the colors of a 3-color LED.
    """

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> (
        bool):
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.RGBLEDWrite(addr,
                                                         red_percent,
                                                         green_percent,
                                                         blue_percent,
                                                         CanInterface.next_uuid()) == 0

    def request_version(self) -> bool:
        pellet = self._tgt2addr(Target.PELLET_DEVICE)
        magnet = self._tgt2addr(Target.MAGNET_DEVICE)

        pellet = pellet is not None and \
                 self._jc.BootloaderCommand(pellet,
                                            JerryCANBootloaderCmd.SubCommand.VERSION)
        magnet = magnet is not None and \
                 self._jc.BootloaderCommand(magnet,
                                            JerryCANBootloaderCmd.SubCommand.VERSION)

        return pellet & magnet

    # NOTE: E-Stop is not implemented in the target
    # def emergency_stop(self) -> bool:
    #  return self.is_open and self._jc.EStop() == 0

    """
    Translate from a JerryCANCmd class to a class specific to the data type received
    """

    def _translate(self, message) -> typing.Any:
        global _audio

        # print (message.type, message.dst_id)
        if message.type == JerryCANCmdType.HEARTBEAT:
            # print("HEARTBEAT")
            heartbeat = Heartbeat()
            heartbeat.target = _addr2tgt(message.dst_id)
            return heartbeat

        elif message.type == JerryCANCmdType.BOOTLOADER_RESPONSE:
            # print("BOOTLOADER")
            if (message.bootloader_response.type ==
                JerryCANBootloaderCmd.SubCommand.VERSION):
                target = _addr2tgt(message.dst_id)
                return Version(target,
                               target_to_str(target) + ': ' + \
                               str(message.bootloader_response.version.running_major) + '.' + \
                               str(message.bootloader_response.version.running_minor) + '.' + \
                               str(message.bootloader_response.version.running_patch))

        elif (message.type == JerryCANCmdType.CFG_RESPONSE and message.cfg_response.type ==
              JerryCANCfgMsg.Type.SERVO):
            # print("SERVO CONFIG")
            target = _addr2tgt(message.dst_id)
            motor = _id_to_motor(target, True, message.cfg_response.servo.motor_id)

            # Not all configuration items get pushed/pulled to the target
            # Reminder: config points to same object after assignment
            config = self.get_motor_configuration(motor)

            config.minimum_position = message.cfg_response.servo.min_position
            config.maximum_position = message.cfg_response.servo.max_position
            config.minimum_pwm_duration = message.cfg_response.servo.min_pwm_duration_us
            config.maximum_pwm_duration = message.cfg_response.servo.max_pwm_duration_us
            config.maximum_velocity = message.cfg_response.servo.motor_max_velocity
            config.maximum_acceleration = message.cfg_response.servo.motor_max_acceleration

            return config

        elif (message.type == JerryCANCmdType.CFG_RESPONSE and message.cfg_response.type ==
              JerryCANCfgMsg.Type.STEPPER):
            # print("STEPPER CONFIG")

            target = _addr2tgt(message.dst_id)
            motor = _id_to_motor(target, False, message.cfg_response.stepper.motor_id)

            config = self.get_motor_configuration(motor)

            config.microsteps = message.cfg_response.stepper.microsteps
            config.steps_per_revolution = message.cfg_response.stepper.steps_per_revolution
            config.flip_limit_orientation = message.cfg_response.stepper.flip_limit_orientation
            config.maximum_velocity = turns_to_mm(message.cfg_response.stepper.motor_max_velocity)
            config.maximum_acceleration = turns_to_mm(
                message.cfg_response.stepper.motor_max_acceleration)
            return config

        elif message.type == JerryCANCmdType.GPIO_READ:
            # print("GPIO READ")
            if _is_magnet_by_addr(message.dst_id):
                gpios = MagnetDigitalInputs()
                gpios.target = message.dst_id

                gpios.continuity_0 = ((message.gpio_read.state & 0x10) != 0)
                gpios.continuity_1 = ((message.gpio_read.state & 0x20) != 0)

                return gpios
            else:
                gpios = PelletDigitalInputs()
                gpios.target = _addr2tgt(message.dst_id)

                gpios.stimulus_1 = ((message.gpio_read.state & 0x010) != 0)
                gpios.stimulus_2 = ((message.gpio_read.state & 0x020) != 0)
                gpios.stimulus_3 = ((message.gpio_read.state & 0x040) != 0)
                gpios.stimulus_4 = ((message.gpio_read.state & 0x080) != 0)

                return gpios

        elif message.type == JerryCANCmdType.TONE:
            # print("TONE")
            tone = Tone()

            tone.target = _addr2tgt(message.dst_id)
            tone.time_remaining_ms = message.tone.duration_ms
            tone.frequency_hz = message.tone.frequency_hz

            return tone

        elif message.type == JerryCANCmdType.ANALOG_OUT:
            # print("ANALOG_OUT")
            if message.analog_out.instance == 0 and _is_pellet_by_addr(message.dst_id):
                analog = AnalogOutput()

                analog.target = _addr2tgt(message.dst_id)
                analog.status_out_mv = message.analog_out.value_mv
                return analog

        elif message.type == JerryCANCmdType.LOAD_CELL_READ:
            # print("LOAD CELL")
            loadcell = LoadCellReading()

            loadcell.target = _addr2tgt(message.dst_id)
            loadcell.load = float(message.load_cell_read.load_mv) / 100.0

            return loadcell

        elif message.type == JerryCANCmdType.PRESSURE_READ:
            # print("PRESSURE")
            pressure = PressureReading()

            pressure.target = _addr2tgt(message.dst_id)
            if message.pressure_read.error != 0:
                pressure.pressure_mv = float(message.pressure_read.pressure_mv) / 100.0
            else:
                pressure.pressure = 0

            return pressure

        elif message.type == JerryCANCmdType.RGB_LED:
            # print("RGB LED")
            led = ColorLed()

            led.target = _addr2tgt(message.dst_id)
            led.red = message.rgb_led.red
            led.green = message.rgb_led.green
            led.blue = message.rgb_led.blue

            return led

        elif message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_BEGIN:
            # print("AUDIO BEGIN")
            _audio.magnitudes.clear()
            _audio.target = _addr2tgt(message.dst_id)
            _audio.packet_id = message.audio_data_cmd.stream_id
            _audio.when = time.time()
            _audio.index = time.perf_counter_ns()

        elif message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_CONT:
            # print("AUDIO CONT")
            if _audio.packet_id != 0 and _audio.target is _addr2tgt(message.dst_id):
                _audio.magnitudes.extend(message.audio_data.magnitudes)

        elif message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_END:
            # print("AUDIO END")
            a = None
            if len(
                _audio.magnitudes) == 32 and message.audio_data_cmd.stream_id == _audio.packet_id:
                a = AudioData()
                a.magnitudes = _audio.magnitudes.copy()
                a.packet_id = _audio.packet_id
                a.target = _audio.target

            _audio.magnitudes.clear()
            _audio.packet_id = 0

            return a

        elif message.type == JerryCANCmdType.DOOR_SENSOR:
            # print("DOOR")
            door = DoorData()
            door.target = _addr2tgt(message.dst_id)

            # reported state is inverse of requested state. See gym_device.py
            door.open_state = [
                message.doors.opened & 0x1 == 0,
                message.doors.opened & 0x2 == 0,
                message.doors.opened & 0x4 == 0,
            ]

            return door

        elif message.type == JerryCANCmdType.SERVO_STATUS:
            # print("SERVO STAT")
            target = _addr2tgt(message.dst_id)
            motor = _id_to_motor(target, True, message.servo_status.motor_id)

            if motor is Motor.NONE:
                return None

            status = ServoStatus(target, motor, message.servo_status.position)

            return status

        elif message.type == JerryCANCmdType.STEPPER_STATUS:
            # print("STEPPER STAT")
            target = _addr2tgt(message.dst_id)
            motor = _id_to_motor(target, False, message.servo_status.motor_id)

            if motor is Motor.NONE:
                return None

            status = StepperStatus(target, motor,
                                   turns_to_mm(message.stepper_status.position),
                                   message.stepper_status.limit_switch)

            return status

        elif message.type == JerryCANCmdType.TEMP_HUM_READ:
            status = SensorStatus()
            status.target = _addr2tgt(message.dst_id)
            status.temperature_c = float(message.temp_hum_read.temperature) / 100.0
            status.humidity_percent = float(message.temp_hum_read.humidity) / 100.0

            return status

        elif message.type == JerryCANCmdType.ACKNOWLEDGE:
            ack = Acknowledge()
            ack.uuid = message.uuid
            return ack

        return None
