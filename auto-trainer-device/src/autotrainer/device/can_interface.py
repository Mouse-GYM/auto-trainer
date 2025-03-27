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
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, AbsOrRel
except (ModuleNotFoundError, TypeError, AttributeError):
    pass

from .device_interface import *

logger = logging.getLogger(__name__)

_MAGNET_SERVO_ID = 0

_PELLET_X_MOTOR_ID = 0
_PELLET_Y_MOTOR_ID = 1
_PELLET_Z_MOTOR_ID = 2

_PELLET_COVER_SERVO_ID = 0
_PELLET_LOAD_SERVO_ID = 1

_audio = AudioData()

'''
Pellet device CAN address board type is 0 (bits 2 and 3)
'''


def _is_pellet_by_addr(addr: int) -> bool:
    return addr & 0xC == 0


'''
Pellet device CAN address board type is 4 (bits 2 and 3)
'''


def _is_magnet_by_addr(addr: int) -> bool:
    return addr & 0xC == 0x04


'''
Convert a CANbus address to a target type
'''


def _addr2tgt(addr: int) -> Target:
    return Target.PELLET_DEVICE if _is_pellet_by_addr(addr) else Target.MAGNET_DEVICE


'''
Given a target type, return an equivalent human-readable string
'''


def target_to_str(target: Target) -> str:
    if target is Target.PELLET_DEVICE:
        return "Pellet"
    elif target is Target.MAGNET_DEVICE:
        return "Magnet"
    else:
        return "Unknown"


'''
Given a motor type, return an equivalent human-readable string
'''


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


'''
Given a motor type, return the Alagus hardware motor identification number
'''


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


def is_servo(motor: Motor) -> bool:
    return motor is Motor.MAGNET_SERVO or \
        motor is Motor.PELLET_LOAD_SERVO or \
        motor is Motor.PELLET_COVER_SERVO


def is_stepper(motor: Motor) -> bool:
    return not is_servo(motor)


def target_of_motor(motor: Motor) -> Target:
    return Target.MAGNET_DEVICE if motor is Motor.MAGNET_SERVO else Target.PELLET_DEVICE


'''
Given a Alagus hardware motor identification number and target, return the motor type
'''


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


'''
Translate from a JerryCANCmd class to a class specific to the data type received
'''


def _translate(message) -> typing.Any:
    global _audio

    # print (message.type, message.dst_id)
    if message.type == JerryCANCmdType.HEARTBEAT:
        # print("HEARTBEAT")
        heartbeat = Heartbeat()
        heartbeat.target = _addr2tgt(message.dst_id)
        return heartbeat

    elif (message.type == JerryCANCmdType.CFG_RESPONSE and message.cfg_response.type ==
          JerryCANCfgMsg.Type.SERVO):
        # print("SERVO CONFIG")
        config = ServoConfig()
        config.target = _addr2tgt(message.dst_id)

        config.motor = _id_to_motor(config.target, True, message.cfg_response.servo.motor_id)
        config.error = message.cfg_response.servo.error == 1

        config.min_position = message.cfg_response.servo.min_position
        config.max_position = message.cfg_response.servo.max_position
        config.min_pwm = message.cfg_response.servo.min_pwm_duration_us
        config.max_pwm = message.cfg_response.servo.max_pwm_duration_us

        return config

    elif (message.type == JerryCANCmdType.CFG_RESPONSE and message.cfg_response.type ==
          JerryCANCfgMsg.Type.STEPPER):
        # print("STEPPER CONFIG")
        config = StepperConfig()
        config.target = _addr2tgt(message.dst_id)

        config.motor = _id_to_motor(config.target, False, message.cfg_response.stepper.motor_id)
        config.error = message.cfg_response.stepper.error

        config.min_step_inverse = message.cfg_response.stepper.min_step_inverse
        config.steps_per_revolution = message.cfg_response.stepper.steps_per_revolution
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
        loadcell.load_mv = float(message.load_cell_read.load_mv) / 100.0

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

    elif message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_CONT:
        # print("AUDIO CONT")
        if _audio.packet_id != 0 and _audio.target is _addr2tgt(message.dst_id):
            _audio.magnitudes.extend(message.audio_data.magnitudes)

    elif message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_END:
        # print("AUDIO END")
        a = None
        if len(_audio.magnitudes) == 32 and message.audio_data_cmd.stream_id == _audio.packet_id:
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

        door.open_state = [
            message.doors.opened & 0x1 != 0,
            message.doors.opened & 0x2 != 0,
            message.doors.opened & 0x4 != 0,
        ]

        return door

    elif message.type == JerryCANCmdType.SERVO_STATUS:
        # print("SERVO STAT")
        target = _addr2tgt(message.dst_id)
        motor = _id_to_motor(target, True, message.servo_status.motor_id)
        status = ServoStatus(target, motor, message.servo_status.position)

        return status

    elif message.type == JerryCANCmdType.STEPPER_STATUS:
        # print("STEPPER STAT")
        target = _addr2tgt(message.dst_id)
        motor = _id_to_motor(target, False, message.servo_status.motor_id)

        status = StepperStatus(target, motor, message.stepper_status.position,
                               message.stepper_status.limit_switch)

        return status

    elif message.type == JerryCANCmdType.TEMP_HUM_READ:
        status = SensorStatus()
        status.target = _addr2tgt(message.dst_id)
        status.temperature_c = float(message.temp_hum_read.temperature) / 100.0
        status.humidity_percent = float(message.temp_hum_read.humidity) / 100.0

        return status

    return None


class CanInterface(DeviceInterface):
    """
    CanInterface implements the details of
        * communication (read and write) with Alogus hardware interface (pyjerrcan)

    Applications and scripts would generally not interact with this class directly,
    but with the more generalized behavior in the CanDevice class.
    """

    def __init__(self):
        super().__init__()

        try:
            self._jc = JerryCAN()
        except (ModuleNotFoundError, TypeError, AttributeError):
            self._jc = None

        self._is_open = False

        self._pellet_addr: typing.Optional[int] = None
        self._magnet_addr: typing.Optional[int] = None

        self._magnet_config = ServoConfig()
        self._magnet_config.motor = Motor.MAGNET_SERVO

        self._load_arm_config = ServoConfig()
        self._load_arm_config.motor = Motor.PELLET_LOAD_SERVO

        self._barrier_config = ServoConfig()
        self._barrier_config.motor = Motor.PELLET_COVER_SERVO

        self._x_config = StepperConfig()
        self._x_config.motor = Motor.PELLET_X_MOTOR

        self._y_config = StepperConfig()
        self._y_config.motor = Motor.PELLET_Y_MOTOR

        self._z_config = StepperConfig()
        self._z_config.motor = Motor.PELLET_Z_MOTOR

    '''
    Set the pellet CAN address. Used primarily for testing, as after data is received
    from the device(s), the address for each target will be updated automatically.
    '''

    def _set_pellet_address(self, addr: int):
        self._pellet_addr = addr
        logger.info(f"pellet module located at {self._pellet_addr}")

    '''
    Set the magnet CAN address. Used primarily for testing, as after data is received
    from the device(s), the address for each target will be updated automatically.
    '''

    def _set_magnet_address(self, addr: int):
        self._magnet_addr = addr
        logger.info(f"magnet module located at {self._magnet_addr}")

    '''
    Determine if both the magnet and pellet CANbus addresses are valid
    '''

    def are_addresses_valid(self) -> bool:
        return self._magnet_addr is not None and self._pellet_addr is not None

    '''
    Return the CANbus address of the given target
    '''

    def _tgt2addr(self, target: Target) -> int:
        dst = self._pellet_addr if target is Target.PELLET_DEVICE else self._magnet_addr
        return dst

    '''
    Assign the pellet or magnet CANbus address based on an incoming message. Each
    target address is set only once.
    '''

    def _assign_address(self, message):
        if self._pellet_addr is None and _is_pellet_by_addr(message.dst_id):
            self._set_pellet_address(message.dst_id)
            self._configure_pellet()

        if self._magnet_addr is None and _is_magnet_by_addr(message.dst_id):
            self._set_magnet_address(message.dst_id)
            self._configure_magnet()

    '''
    Flag: interface to hardware is open (true) or closed (false)
    '''

    @property
    def is_open(self) -> bool:
        return self._is_open

    '''
    Open the interface (CANbus) connection
    '''

    def open(self) -> bool:
        if self._jc is None:
            return False

        self._is_open = self._jc.Open() == 0

        return self._is_open

    '''
    Close the interface (CANbus) connection
    '''

    def close(self):
        if self._is_open:
            self._jc.Close()

    '''
    Flag: Data can be read from the connection
    '''

    def can_read(self) -> bool:
        return self._is_open

    '''
    Read a set of packets from the CANbus.
    Returns a list of data classes (see device_interface.py for list of classes)
    '''

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
                time.sleep(0.0001)

        return [x for x in map(_translate, messages) if x is not None]

    '''
    Do not allow the application to write unknown messages to the CANbus
    '''

    def write(self, value: typing.Any) -> int:
        raise NotImplementedError()

    '''
    Do not allow the application to write unknown messages to the CANbus
    '''

    def write_str(self, value: str) -> int:
        raise NotImplementedError()

    '''
    Read data until a specific response is detected
    '''

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

    '''
    Set a motor's configuration. Only one of servo_config or stepper_config
    should be set.
    '''

    def set_motor_configuration(self, motor: Motor, servo_config=None,
                                stepper_config=None) -> bool:
        if servo_config is None:
            servo_config = ServoConfig()
        if stepper_config is None:
            stepper_config = StepperConfig()

        rc = False

        if motor is Motor.MAGNET_SERVO:
            self._magnet_config = servo_config
            self._magnet_config.motor = motor
            rc = self.write_servo_config(self._magnet_config)

        elif motor is Motor.PELLET_X_MOTOR:
            self._x_config = stepper_config
            self._x_config.motor = motor
            rc = self.write_stepper_config(self._x_config)

        elif motor is Motor.PELLET_Y_MOTOR:
            self._y_config = stepper_config
            self._y_config.motor = motor
            rc = self.write_stepper_config(self._y_config)

        elif motor is Motor.PELLET_Z_MOTOR:
            self._z_config = stepper_config
            self._z_config.motor = motor
            rc = self.write_stepper_config(self._z_config)

        elif motor is Motor.PELLET_COVER_SERVO:
            self._barrier_config = servo_config
            self._barrier_config.motor = motor
            rc = self.write_servo_config(self._barrier_config)

        elif motor is Motor.PELLET_LOAD_SERVO:
            self._load_arm_config = servo_config
            self._load_arm_config.motor = motor
            rc = self.write_servo_config(self._load_arm_config)

        # wait for write to complete
        if rc:
            time.sleep(1)

        return rc

    '''
    Write the currently-known configuration for each of the pellet board's motors. 
    '''

    def _configure_pellet(self):
        self.set_motor_configuration(Motor.PELLET_LOAD_SERVO, servo_config=self._load_arm_config)
        self.set_motor_configuration(Motor.PELLET_COVER_SERVO, servo_config=self._barrier_config)
        self.set_motor_configuration(Motor.PELLET_X_MOTOR, stepper_config=self._x_config)
        self.set_motor_configuration(Motor.PELLET_Y_MOTOR, stepper_config=self._y_config)
        self.set_motor_configuration(Motor.PELLET_Z_MOTOR, stepper_config=self._z_config)

    '''
    Write the currently-known configuration for each of the magnet board's motors. 
    '''

    def _configure_magnet(self):
        self.set_motor_configuration(Motor.MAGNET_SERVO, servo_config=self._magnet_config)

    '''
    Tare the load cell so the current reading is 0.
    '''

    def tare_load_cell(self) -> bool:
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.LoadCellTare(addr, 0) == 0

    '''
    Tare the pressure sensor so the current reading is 0.
    '''

    def tare_pressure_sensor(self) -> bool:
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.PressureSensorTare(addr, 0) == 0

    '''
    Set the position of the magnet motor
    '''

    def set_magnet(self, position: int) -> bool:
        if position < 0:
            position = 0
        elif position > 180:
            position = 180

        logger.info(f"set magnet position {position}")
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.ServoMove(addr, _MAGNET_SERVO_ID,
                                                       position, self._magnet_config.max_velocity,
                                                       self._magnet_config.max_acceleration,
                                                       AbsOrRel.ABSOLUTE) == 0

    '''
    Set the position of the X-direction motor
    '''

    def set_x(self, position: float) -> bool:
        if position > 0:
            position = 0
        elif position < -12:
            position = -12

        logger.info(f"set pellet absolute x {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.StepperMove(addr, _PELLET_X_MOTOR_ID,
                                                         position,
                                                         self._x_config.max_velocity,
                                                         self._x_config.max_acceleration,
                                                         AbsOrRel.ABSOLUTE) == 0

    '''
    Set the position of the Y-direction motor
    '''

    def set_y(self, position: float):
        if position < 0:
            position = 0
        elif position > 12:
            position = 12

        logger.info(f"set pellet absolute y {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.StepperMove(addr, _PELLET_Y_MOTOR_ID,
                                                         position,
                                                         self._y_config.max_velocity,
                                                         self._y_config.max_acceleration,
                                                         AbsOrRel.ABSOLUTE) == 0

    '''
    Set the position of the Z-direction motor
    '''

    def set_z(self, position: float):
        if position < 0:
            position = 0
        elif position > 12:
            position = 12

        logger.info(f"set pellet absolute z {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)

        return addr is not None and self._jc.StepperMove(addr, _PELLET_Z_MOTOR_ID,
                                                         position,
                                                         self._z_config.max_velocity,
                                                         self._z_config.max_acceleration,
                                                         AbsOrRel.ABSOLUTE) == 0

    '''
    Set the position of the load arm
    '''

    def set_load(self, position: float):
        if position < 0:
            position = 0
        elif position > 120:
            position = 120

        logger.info(f"set load arm {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ServoMove(addr, _PELLET_LOAD_SERVO_ID,
                                                       position,
                                                       self._load_arm_config.max_velocity,
                                                       self._load_arm_config.max_acceleration,
                                                       AbsOrRel.ABSOLUTE) == 0

    '''
    Set the position of the barrier/cover for pellet delivery
    '''

    def set_barrier(self, position):
        if position < 0:
            position = 0
        elif position > 180:
            position = 180

        logger.info(f"set barrier arm {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ServoMove(addr, _PELLET_COVER_SERVO_ID,
                                                       position,
                                                       self._barrier_config.max_velocity,
                                                       self._barrier_config.max_acceleration,
                                                       AbsOrRel.ABSOLUTE) == 0

    '''
    Open the cover so the pellet is visible to the animal
    '''

    def release_pellet(self) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)

        return addr is not None and self.set_barrier(self._barrier_config.min_position) and \
            self.emit_tone(addr, 6000)

    '''
    Open the cover so the pellet is visible to the animal
    '''

    def cover_pellet(self) -> bool:
        logger.info(f"cover pellet {self._barrier_config.max_position}")
        return self.set_barrier(self._barrier_config.max_position)

    '''
    Send the given motor (X, Y, or Z) to the 0 position
    '''

    def stepper_home(self, motor: Motor) -> bool:
        logger.info(f"Homing Stepper Motor {motor.value}")
        if is_servo(motor):
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)

        # Third arg - forward/rev. Only X is fwd; others are reverse
        return addr is not None and self._jc.StepperHome(addr, _motor_to_id(motor),
                                                         motor == Motor.PELLET_X_MOTOR) == 0

    '''
    Update a stepper motor configuration on the target
    '''

    def write_stepper_config(self, config: StepperConfig) -> bool:
        motor_id = _motor_to_id(config.motor)
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        if addr is None:
            return False

        if self._jc.StepperCfgWrite(addr, motor_id,
                                    config.min_step_inverse,
                                    config.steps_per_revolution) == 0:
            logger.debug(
                f"stepper {addr} {motor_id} config write: {config.min_step_inverse} {config.steps_per_revolution}")
            return True
        else:
            logger.error(
                f"stepper {addr} {motor_id} config write failed")
            return False

    '''
    Update a servo motor configuration on the target
    '''

    def write_servo_config(self, config: ServoConfig) -> bool:
        motor_id = _motor_to_id(config.motor)
        target = target_of_motor(config.motor)

        addr = self._tgt2addr(target)
        if addr is None:
            return False

        if self._jc.ServoCfgWrite(addr, motor_id,
                                  config.min_position,
                                  config.max_position,
                                  config.min_pwm_duration_us,
                                  config.max_pwm_duration_us) == 0:
            logger.debug(
                f"servo {addr} {motor_id} config write: {config.min_position}"
                f" {config.max_position} {config.min_pwm_duration_us} "
                f"{config.max_pwm_duration_us}")
            return True
        else:
            logger.error(
                f"servo {addr} {motor_id} config write failed")
            return False

    '''
    Request a stepper motor configuration from a target
    '''

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

    '''
    Send a heartbeat message to the target; causes an LED to blink briefly.
    '''

    def send_heartbeat(self) -> bool:
        return self._jc.Heartbeat() == 0

    '''
    Set a digital output value on the pellet device
    '''

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
        return addr is not None and self._jc.GPIOWrite(addr, 0, gpio_id, state) == 0

    '''
    Emit a tone for the animal to hear
    '''

    def emit_tone(self, frequency: int, duration_ms: int = 1000) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ToneWrite(addr, 0, frequency,
                                                       duration_ms) == 0

    '''
    Set an analog output on the pellet device
    '''

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.AnalogOutWrite(addr, int(channel.value),
                                                            millivolts) == 0

    '''
    Set the colors of a 3-color LED.
    '''

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.RGBLEDWrite(addr, red_percent, green_percent,
                                                         blue_percent) == 0

    # NOTE: E-Stop is not implemented in the target
    # def emergency_stop(self) -> bool:
    #  return self.is_open and self._jc.EStop() == 0
