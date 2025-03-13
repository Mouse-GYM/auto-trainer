import logging
import time
import typing
from dataclasses import dataclass
from enum import Enum

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, AbsOrRel
except:
    pass

from .device_interface import DeviceInterface

logger = logging.getLogger(__name__)

MAGNET_MOTOR_ID = 0

PELLET_X_MOTOR_ID = 0
PELLET_Y_MOTOR_ID = 1
PELLET_Z_MOTOR_ID = 2

PELLET_COVER_SERVO_ID = 0
PELLET_LOAD_SERVO_ID = 1


@dataclass
class Target(Enum):
    PELLET_DEVICE = 0
    MAGNET_DEVICE = 1


@dataclass
class DigitalOutputs(Enum):
    STIMULUS_1 = 1
    STIMULUS_2 = 2
    STIMULUS_3 = 3
    STIMULUS_4 = 4


@dataclass
class AnalogOutputs(Enum):
    STATUS_OUT = 0


@dataclass
class Source:
    target: Target = None


@dataclass
class Heartbeat(Source):
    unused: bool = False


@dataclass
class MagnetDigitalInputs(Source):
    continuity_0 = False
    continuity_1 = False


@dataclass
class PelletDigitalInputs(Source):
    stimulus_1 = False
    stimulus_2 = False
    stimulus_3 = False
    stimulus_4 = False


@dataclass
class ServoConfig(Source):
    motor_id: int = -1
    error: bool = False
    min_position: float = 0
    max_position: float = 100
    min_pwm_duration_us: float = 1000
    max_pwm_duration_us: float = 2000

    max_vel: float = 25.0
    max_acc: float = 100.0

    @classmethod
    def from_dict(cls, data: dict):
        config = ServoConfig()

        if "min_pos" in data:
            config.min_position = data["min_pos"]
        if "max_pos" in data:
            config.max_position = data["max_pos"]
        if "min_pwm" in data:
            config.min_pwm = data["min_pwm"]
        if "max_pwm" in data:
            config.max_pwm = data["max_pwm"]
        if "max_vel" in data:
            config.max_vel = data["max_vel"]
        if "max_acc" in data:
            config.max_acc = data["max_acc"]

        return config


@dataclass
class ServoStatus(Source):
    motor_id: int = 0
    position: float = 0


@dataclass
class StepperConfig(Source):
    motor_id: int = -1
    error: bool = False
    min_step_inverse: int = 64
    steps_per_revolution: float = 48.0

    max_vel: float = 25.0
    max_acc: float = 100.0

    @classmethod
    def from_dict(cls, data: dict):
        config = StepperConfig()

        if "min_step_inverse" in data:
            config.min_step_inverse = data["min_step_inverse"]
        if "steps_per_revolution" in data:
            config.steps_per_revolution = data["steps_per_revolution"]
        if "max_vel" in data:
            config.max_vel = data["max_vel"]
        if "max_acc" in data:
            config.max_acc = data["max_acc"]

        return config


@dataclass
class StepperStatus(Source):
    motor_id: int = 0
    position: float = 0
    limit_switch: bool = False


@dataclass
class Tone(Source):
    time_remaining_ms: int = 0
    frequency_hz: int = 0


@dataclass
class AnalogOutput(Source):
    status_out_mv: int = 0


@dataclass
class LoadCellReading(Source):
    load: float = 0


@dataclass
class PressureReading(Source):
    pressure: float = 0


@dataclass
class ColorLed(Source):
    red: int = 0
    green: int = 0
    blue: int = 0


@dataclass
class AudioData(Source):
    packet_id: int = 0
    magnitudes = []


@dataclass
class DoorData(Source):
    open_state = [False, False, False]


@dataclass
class Status(Source):
    unused: bool = True


@dataclass
class SensorStatus(Source):
    temperature_c: float = 0
    humidity_percent: float = 0


def is_pellet_by_addr(addr: int) -> bool:
    return addr < 4


def is_magnet_by_addr(addr: int) -> bool:
    return not is_pellet_by_addr(addr)


def addr2tgt(addr: int) -> Target:
    return Target.PELLET_DEVICE if is_pellet_by_addr(addr) else Target.MAGNET_DEVICE


_audio = AudioData()


def _translate(message) -> typing.Any:
    global _audio

    # print (message.type, message.dst_id)
    if message.type == JerryCANCmdType.HEARTBEAT:
        # print("HEARTBEAT")
        heartbeat = Heartbeat()
        heartbeat.target = addr2tgt(message.dst_id)
        return heartbeat

    if message.type == JerryCANCmdType.CFG_RESPONSE and message.cfg_response.type == JerryCANCfgMsg.Type.SERVO:
        # print("SERVO CONFIG")
        config = ServoConfig()
        config.target = addr2tgt(message.dst_id)

        config.motor_id = message.cfg_response.servo.motor_id
        config.error = message.cfg_response.servo.error == 1

        config.min_position = message.cfg_response.servo.min_position
        config.max_position = message.cfg_response.servo.max_position
        config.min_pwm = message.cfg_response.servo.min_pwm_duration_us
        config.max_pwm = message.cfg_response.servo.max_pwm_duration_us

        return config

    if (message.type == JerryCANCmdType.CFG_RESPONSE and message.cfg_response.type ==
        JerryCANCfgMsg.Type.STEPPER):
        # print("STEPPER CONFIG")
        config = StepperConfig()
        config.target = addr2tgt(message.dst_id)

        config.motor_id = message.cfg_response.stepper.motor_id
        config.error = message.cfg_response.stepper.error

        config.min_step_inverse = message.cfg_response.stepper.min_step_inverse
        config.steps_per_revolution = message.cfg_response.stepper.steps_per_revolution
        return config

    if message.type == JerryCANCmdType.GPIO_READ:
        # print("GPIO READ")
        if is_magnet_by_addr(message.dst_id):
            gpios = MagnetDigitalInputs()
            gpios.target = message.dst_id

            gpios.continuity_0 = ((message.gpio_read.state & 0x10) != 0)
            gpios.continuity_1 = ((message.gpio_read.state & 0x20) != 0)

            return gpios
        else:
            gpios = PelletDigitalInputs()
            gpios.target = addr2tgt(message.dst_id)

            gpios.stimulus_1 = ((message.gpio_read.state & 0x010) != 0)
            gpios.stimulus_2 = ((message.gpio_read.state & 0x020) != 0)
            gpios.stimulus_3 = ((message.gpio_read.state & 0x040) != 0)
            gpios.stimulus_4 = ((message.gpio_read.state & 0x080) != 0)

            return gpios

    if message.type == JerryCANCmdType.TONE:
        # print("TONE")
        tone = Tone()

        tone.target = addr2tgt(message.dst_id)
        tone.time_remaining_ms = message.tone.duration_ms
        tone.frequency_hz = message.tone.frequency_hz

        return tone

    if message.type == JerryCANCmdType.ANALOG_OUT:
        # print("ANALOG_OUT")
        if message.analog_out.instance == 0 and is_pellet_by_addr(message.dst_id):
            analog = AnalogOutput()

            analog.target = addr2tgt(message.dst_id)
            analog.status_out_mv = message.analog_out.value_mv
            return analog

    if message.type == JerryCANCmdType.LOAD_CELL_READ:
        # print("LOAD CELL")
        loadcell = LoadCellReading()

        loadcell.target = addr2tgt(message.dst_id)
        loadcell.load_mv = float(message.load_cell_read.load_mv) / 100.0

        return loadcell

    if message.type == JerryCANCmdType.PRESSURE_READ:
        # print("PRESSURE")
        pressure = PressureReading()

        pressure.target = addr2tgt(message.dst_id)
        if message.pressure_read.error != 0:
            pressure.pressure = float(message.pressure_read.pressure_mv) / 100.0
        else:
            pressure.pressure = 0

        return pressure

    if message.type == JerryCANCmdType.RGB_LED:
        # print("RGB LED")
        led = ColorLed()

        led.target = addr2tgt(message.dst_id)
        led.red = message.rgb_led.red
        led.green = message.rgb_led.green
        led.blue = message.rgb_led.blue

        return led

    if message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_BEGIN:
        # print("AUDIO BEGIN")
        _audio.magnitudes.clear()
        _audio.target = addr2tgt(message.dst_id)
        _audio.packet_id = message.audio_data_cmd.stream_id

    if message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_CONT:
        # print("AUDIO CONT")
        if _audio.packet_id != 0 and _audio.target == addr2tgt(message.dst_id):
            _audio.magnitudes.extend(message.audio_data.magnitudes)

    if message.type == JerryCANCmdType.AUDIO_MAGNITUDE_DATA_END:
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

    if message.type == JerryCANCmdType.DOOR_SENSOR:
        # print("DOOR")
        door = DoorData()
        door.target = addr2tgt(message.dst_id)

        door.open_state = [
            message.doors.opened & 0x1 != 0,
            message.doors.opened & 0x2 != 0,
            message.doors.opened & 0x4 != 0,
        ]

        return door

    if message.type == JerryCANCmdType.SERVO_STATUS:
        # print("SERVO STAT")
        status = ServoStatus()
        status.target = addr2tgt(message.dst_id)

        status.position = message.servo_status.position
        status.motor_id = message.servo_status.motor_id
        return status

    if message.type == JerryCANCmdType.STEPPER_STATUS:
        # print("STEPPER STAT")
        status = StepperStatus()
        status.target = addr2tgt(message.dst_id)

        status.position = message.stepper_status.position
        status.limit_switch = message.stepper_status.limit_switch
        status.motor_id = message.stepper_status.motor_id

        return status

    if message.type == JerryCANCmdType.TEMP_HUM_READ:
        status = SensorStatus()
        status.target = addr2tgt(message.dst_id)
        status.temperature_c = float(message.temp_hum_read.temperature) / 100.0
        status.pressure_percent = float(message.temp_hum_read.pressure) / 100.0

        print(f"{status.temperature_c} {status.pressure_percent}")
        return status
    return None


class WhiskerInterface(DeviceInterface):
    """
    Somewhat temporary attempt to confirm the Alogus hardware to the existing device hardware interface.  Will likely
    change substantially.

    WhiskerInterface implements the details of
        * communication (read and write) with Alogus hardware interface (pyjerrcan)

    Applications and scripts would generally not interact with this class directly, but with the more generalized
    behavior in the WhiskerDevice class.
    """

    def __init__(self, magnet_config: typing.Optional[ServoConfig] = None,
                 barrier_config: typing.Optional[ServoConfig] = None,
                 load_arm_config: typing.Optional[ServoConfig] = None,
                 x_config: typing.Optional[StepperConfig] = None,
                 y_config: typing.Optional[StepperConfig] = None,
                 z_config: typing.Optional[StepperConfig] = None):
        super().__init__()

        try:
            self._jc = JerryCAN()
        except:
            self._jc = None

        self._is_open = False

        self._pellet_addr: typing.Optional[int] = None
        self._magnet_addr: typing.Optional[int] = None

        self._magnet_config = magnet_config
        if self._magnet_config is None:
            self._magnet_config = ServoConfig()
        self._magnet_config.motor_id = MAGNET_MOTOR_ID

        self._load_arm_config = load_arm_config
        if self._load_arm_config is None:
            self._load_arm_config = ServoConfig()
        self._load_arm_config.motor_id = PELLET_LOAD_SERVO_ID

        self._barrier_config = barrier_config
        if self._barrier_config is None:
            self._barrier_config = ServoConfig()
        self._barrier_config.motor_id = PELLET_COVER_SERVO_ID

        self._x_config = x_config
        if self._x_config is None:
            self._x_config = StepperConfig()
        self._x_config.motor_id = PELLET_X_MOTOR_ID

        self._y_config = y_config
        if self._y_config is None:
            self._y_config = StepperConfig()
        self._y_config.motor_id = PELLET_Y_MOTOR_ID

        self._z_config = z_config
        if self._z_config is None:
            self._z_config = StepperConfig()
        self._z_config.motor_id = PELLET_Z_MOTOR_ID

    def is_pellet(self, addr: int):
        return self.is_same_target(Target.PELLET_DEVICE, addr)

    def is_magnet(self, addr: int):
        return self.is_same_target(Target.MAGNET_DEVICE, addr)

    def set_pellet_address(self, addr: int):
        self._pellet_addr = addr

    def set_magnet_address(self, addr: int):
        self._magnet_addr = addr

    def tgt2addr(self, target: Target) -> int:
        dst = self._pellet_addr if target == Target.PELLET_DEVICE else self._magnet_addr
        if dst is None:
            exit("Pellet or Magnet CAN IDs not configured.")
        return dst

    def is_same_target(self, target: Target, id: int):
        return target == Target.PELLET_DEVICE and id == self._pellet_addr or \
            target == Target.MAGNET_DEVICE and id == self._magnet_addr

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
                messages.append(message)
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

    def configure_pellet(self):
        self.write_servo_config(Target.PELLET_DEVICE, self._load_arm_config)
        self.write_servo_config(Target.PELLET_DEVICE, self._barrier_config)
        self.write_stepper_config(self._x_config)
        self.write_stepper_config(self._y_config)
        self.write_stepper_config(self._z_config)

    def configure_magnet(self):
        self.write_servo_config(Target.MAGNET_DEVICE, self._magnet_config)

    def tare_load_cell(self) -> bool:
        return self._jc.LoadCellTare(self.tgt2addr(Target.MAGNET_DEVICE), 0) == 0

    def tare_pressure_sensor(self) -> bool:
        return self._jc.PressureSensorTare(self.tgt2addr(Target.MAGNET_DEVICE), 0) == 0

    def set_magnet_intensity(self, intensity: float):
        logger.info(f"set magnet intensity {intensity}")
        self._jc.ServoMove(self.tgt2addr(Target.MAGNET_DEVICE), MAGNET_MOTOR_ID,
                           intensity, self._magnet_config.max_vel, self._magnet_config.max_acc,
                           AbsOrRel.ABSOLUTE)

    def set_x(self, value: float):
        logger.info(f"set pellet absolute x {value}")
        self._jc.StepperMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_X_MOTOR_ID,
                             value,
                             self._x_config.max_vel,
                             self._x_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_y(self, value: float):
        logger.info(f"set pellet absolute y {value}")
        self._jc.StepperMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_Y_MOTOR_ID, value,
                             self._y_config.max_vel,
                             self._y_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_z(self, value: float):
        logger.info(f"set pellet absolute z {value}")
        self._jc.StepperMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_Z_MOTOR_ID, value,
                             self._z_config.max_vel,
                             self._z_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_load(self, value: float):
        logger.info(f"set load arm {value}")
        self._jc.ServoMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_LOAD_SERVO_ID, value,
                           self._load_arm_config.max_vel,
                           self._load_arm_config.max_acc, AbsOrRel.ABSOLUTE)

    def set_barrier(self, value):
        logger.info(f"set barrier arm {value}")
        self._jc.ServoMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_COVER_SERVO_ID, value,
                           self._barrier_config.max_vel,
                           self._barrier_config.max_acc, AbsOrRel.ABSOLUTE)

    def release_pellet(self):
        logger.info(f"release pellet {self._barrier_config.min_pos}")
        self._jc.ServoMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_COVER_SERVO_ID,
                           self._barrier_config.min_pos,
                           self._barrier_config.max_vel, self._barrier_config.max_acc,
                           AbsOrRel.ABSOLUTE)

        self.emit_tone(self.tgt2addr(Target.PELLET_DEVICE), 6000)

    def cover_pellet(self):
        logger.info(f"cover pellet {self._barrier_config.max_pos}")
        self._jc.ServoMove(self.tgt2addr(Target.PELLET_DEVICE), PELLET_COVER_SERVO_ID,
                           self._barrier_config.max_pos,
                           self._barrier_config.max_vel, self._barrier_config.max_acc,
                           AbsOrRel.ABSOLUTE)

    def write_stepper_config(self, config: StepperConfig) -> bool:
        if self._jc.StepperCfgWrite(self.tgt2addr(Target.PELLET_DEVICE), config.motor_id,
                                    config.min_step_inverse,
                                    config.steps_per_revolution) == 0:
            logger.debug(
                f"stepper {self.tgt2addr(Target.PELLET_DEVICE)} {config.motor_id} config write: {config.min_step_inverse} {config.steps_per_revolution}")
            return True
        else:
            logger.error(
                f"stepper {self.tgt2addr(Target.PELLET_DEVICE)} {config.motor_id} config write failed")
            return False

    def write_servo_config(self, target: Target, servo_config: ServoConfig) -> bool:
        if self._jc.ServoCfgWrite(self.tgt2addr(target), servo_config.motor_id,
                                  servo_config.min_position,
                                  servo_config.max_position,
                                  servo_config.min_pwm_duration_us,
                                  servo_config.max_pwm_duration_us) == 0:
            logger.debug(
                f"servo {self.tgt2addr(target)} {servo_config.motor_id} config write: {servo_config.min_position}"
                f" {servo_config.max_position} {servo_config.min_pwm_duration_us} "
                f"{servo_config.max_pwm_duration_us}")
            return True
        else:
            logger.error(
                f"servo {self.tgt2addr(target)} {servo_config.motor_id} config write failed")
            return False

    def request_servo_config(self, target: Target, motor_id: int) -> bool:
        msg = JerryCANCfgMsg()
        msg.type = JerryCANCfgMsg.Type.SERVO
        msg.servo.motor_id = motor_id
        return self._jc.CfgRead(self.tgt2addr(target), msg) == 0

    def request_stepper_config(self, motor_id: int) -> bool:
        msg = JerryCANCfgMsg()
        msg.type = JerryCANCfgMsg.Type.STEPPER
        msg.servo.motor_id = motor_id
        return self._jc.CfgRead(self.tgt2addr(Target.PELLET_DEVICE), msg) == 0

    def heartbeat(self) -> bool:
        return self._jc.Heartbeat() == 0

    def write_gpio(self, gpio: DigitalOutputs, state: bool) -> bool:
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

        return self._jc.GPIOWrite(self.tgt2addr(Target.PELLET_DEVICE), 0, gpio_id, state) == 0

    # NOTE: E-Stop is not implemented in the target
    # def emergency_stop(self) -> bool:
    #  return self.is_open and self._jc.EStop() == 0

    def emit_tone(self, frequency: int, duration_ms: int = 1000) -> bool:
        return self._jc.ToneWrite(self.tgt2addr(Target.PELLET_DEVICE), 0, frequency,
                                  duration_ms) == 0

    def set_analog_output(self, channel: AnalogOutputs, millivolts: int) -> bool:
        return self._jc.AnalogOutWrite(self.tgt2addr(Target.PELLET_DEVICE), int(channel.value),
                                       millivolts) == 0

    def set_color_led(self, red_percent: int, green_percent: int, blue_percent: int) -> bool:
        return self._jc.RGBLEDWrite(self.tgt2addr(Target.PELLET_DEVICE), red_percent,
                                    green_percent, blue_percent) == 0
