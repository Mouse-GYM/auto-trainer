import logging
import time

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, AbsOrRel
except:
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


def _is_pellet_by_addr(addr: int) -> bool:
    return addr < 4


def _is_magnet_by_addr(addr: int) -> bool:
    return not _is_pellet_by_addr(addr)


def _addr2tgt(addr: int) -> Target:
    return Target.PELLET_DEVICE if _is_pellet_by_addr(addr) else Target.MAGNET_DEVICE


def target_to_str(target: Target) -> str:
    if target is Target.PELLET_DEVICE:
        return "Pellet"
    elif target is Target.MAGNET_DEVICE:
        return "Magnet"
    else:
        return "Unknown"


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


def _id_to_motor(target: Target, is_servo: bool, motor_id: int) -> Motor:
    if target is Target.MAGNET_DEVICE:
        if is_servo:
            if motor_id is _MAGNET_SERVO_ID:
                return Motor.MAGNET_SERVO
    else:
        if is_servo:
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
        else:
            print(f"Dropping...{len(_audio.magnitudes)}")

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
        except:
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

    def _set_pellet_address(self, addr: int):
        self._pellet_addr = addr
        logger.info(f"pellet module located at {self._pellet_addr}")

    def _set_magnet_address(self, addr: int):
        self._magnet_addr = addr
        logger.info(f"magnet module located at {self._magnet_addr}")

    def are_addresses_valid(self) -> bool:
        return self._magnet_addr is not None and self._pellet_addr is not None

    @staticmethod
    def is_servo(motor: Motor) -> bool:
        return motor is Motor.MAGNET_SERVO or \
            motor is Motor.PELLET_LOAD_SERVO or \
            motor is Motor.PELLET_COVER_SERVO

    @staticmethod
    def is_stepper(motor: Motor) -> bool:
        return not CanInterface.is_servo(motor)

    @staticmethod
    def target_of_motor(motor: Motor) -> Target:
        return Target.MAGNET_DEVICE if motor is Motor.MAGNET_SERVO else Target.PELLET_DEVICE

    def _is_pellet(self, addr: int):
        return self._is_same_target(Target.PELLET_DEVICE, addr)

    def _is_magnet(self, addr: int):
        return self._is_same_target(Target.MAGNET_DEVICE, addr)

    def _tgt2addr(self, target: Target) -> int:
        dst = self._pellet_addr if target is Target.PELLET_DEVICE else self._magnet_addr
        return dst

    def _is_same_target(self, target: Target, addr: int):
        return target is Target.PELLET_DEVICE and addr == self._pellet_addr or \
            target is Target.MAGNET_DEVICE and addr == self._magnet_addr

    def _assign_address(self, message):
        pellet_destination = 0x00
        magnet_destination = 0x04

        if self._pellet_addr is None and message.dst_id & 0x4 == pellet_destination:
            self._set_pellet_address(message.dst_id)
            self._configure_pellet()

        if self._magnet_addr is None and message.dst_id & 0x4 == magnet_destination:
            self._set_magnet_address(message.dst_id)

            self._configure_magnet()

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> bool:
        if self._jc is None:
            return False

        self._is_open = self._jc.Open() == 0

        return self._is_open

    def close(self):
        if self._is_open:
            self._jc.Close()

    def can_read(self) -> bool:
        return self._is_open

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

    def write(self, value: typing.Any) -> int:
        msg, destination = value
        if self._is_open:
            if self._jc.SendMessage(msg, destination) == 0:
                return 1

        return 0

    def write_str(self, value: str) -> int:
        raise NotImplementedError()

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

    def _configure_pellet(self):
        self.set_motor_configuration(Motor.PELLET_LOAD_SERVO, servo_config=self._load_arm_config)
        self.set_motor_configuration(Motor.PELLET_COVER_SERVO, servo_config=self._barrier_config)
        self.set_motor_configuration(Motor.PELLET_X_MOTOR, stepper_config=self._x_config)
        self.set_motor_configuration(Motor.PELLET_Y_MOTOR, stepper_config=self._y_config)
        self.set_motor_configuration(Motor.PELLET_Z_MOTOR, stepper_config=self._z_config)

    def _configure_magnet(self):
        self.set_motor_configuration(Motor.MAGNET_SERVO, servo_config=self._magnet_config)

    def tare_load_cell(self) -> bool:
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.LoadCellTare(addr, 0) == 0

    def tare_pressure_sensor(self) -> bool:
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.PressureSensorTare(addr, 0) == 0

    def set_magnet(self, position: int) -> bool:
        logger.info(f"set magnet position {position}")
        addr = self._tgt2addr(Target.MAGNET_DEVICE)
        return addr is not None and self._jc.ServoMove(addr, _MAGNET_SERVO_ID,
                                                       position, self._magnet_config.max_velocity,
                                                       self._magnet_config.max_acceleration,
                                                       AbsOrRel.ABSOLUTE) == 0

    def set_x(self, position: float) -> bool:
        logger.info(f"set pellet absolute x {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.StepperMove(addr, _PELLET_X_MOTOR_ID,
                                                         position,
                                                         self._x_config.max_velocity,
                                                         self._x_config.max_acceleration,
                                                         AbsOrRel.ABSOLUTE) == 0

    def set_y(self, position: float):
        logger.info(f"set pellet absolute y {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.StepperMove(addr, _PELLET_Y_MOTOR_ID,
                                                         position,
                                                         self._y_config.max_velocity,
                                                         self._y_config.max_acceleration,
                                                         AbsOrRel.ABSOLUTE) == 0

    def set_z(self, position: float):
        logger.info(f"set pellet absolute z {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)

        return addr is not None and self._jc.StepperMove(addr, _PELLET_Z_MOTOR_ID,
                                                         position,
                                                         self._z_config.max_velocity,
                                                         self._z_config.max_acceleration,
                                                         AbsOrRel.ABSOLUTE) == 0

    def set_load(self, position: float):
        logger.info(f"set load arm {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ServoMove(addr, _PELLET_LOAD_SERVO_ID,
                                                       position,
                                                       self._load_arm_config.max_velocity,
                                                       self._load_arm_config.max_acceleration,
                                                       AbsOrRel.ABSOLUTE) == 0

    def set_barrier(self, position):
        logger.info(f"set barrier arm {position}")
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ServoMove(addr, _PELLET_COVER_SERVO_ID,
                                                       position,
                                                       self._barrier_config.max_velocity,
                                                       self._barrier_config.max_acceleration,
                                                       AbsOrRel.ABSOLUTE) == 0

    def release_pellet(self) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)

        return addr is not None and self.set_barrier(self._barrier_config.min_position) and \
            self.emit_tone(addr, 6000)

    def cover_pellet(self) -> bool:
        logger.info(f"cover pellet {self._barrier_config.max_position}")
        return self.set_barrier(self._barrier_config.max_position)

    def stepper_home(self, motor: Motor) -> bool:
        logger.info(f"Homing Stepper Motor {motor.value}")
        if CanInterface.is_servo(motor):
            return False

        addr = self._tgt2addr(Target.PELLET_DEVICE)

        # Third arg - forward/rev. Only X is fwd; others are reverse
        return addr is not None and self._jc.StepperHome(addr, _motor_to_id(motor),
                                                         motor == Motor.PELLET_X_MOTOR)

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

    def write_servo_config(self, config: ServoConfig) -> bool:
        motor_id = _motor_to_id(config.motor)
        target = CanInterface.target_of_motor(config.motor)

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

    def request_motor_config(self, motor: Motor) -> bool:
        target = CanInterface.target_of_motor(motor)
        msg = JerryCANCfgMsg()
        if CanInterface.is_servo(motor):
            msg.type = JerryCANCfgMsg.Type.SERVO
            msg.servo.motor_id = _motor_to_id(motor)
        else:
            msg.type = JerryCANCfgMsg.Type.STEPPER
            msg.stepper.motor_id = _motor_to_id(motor)

        addr = self._tgt2addr(target)
        return addr is not None and self._jc.CfgRead(addr, msg) == 0

    def send_heartbeat(self) -> bool:
        return self._jc.Heartbeat() == 0

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

    # NOTE: E-Stop is not implemented in the target
    # def emergency_stop(self) -> bool:
    #  return self.is_open and self._jc.EStop() == 0

    def emit_tone(self, frequency: int, duration_ms: int = 1000) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.ToneWrite(addr, 0, frequency,
                                                       duration_ms) == 0

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.AnalogOutWrite(addr, int(channel.value),
                                                            millivolts) == 0

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        addr = self._tgt2addr(Target.PELLET_DEVICE)
        return addr is not None and self._jc.RGBLEDWrite(addr, red_percent, green_percent,
                                                         blue_percent) == 0
