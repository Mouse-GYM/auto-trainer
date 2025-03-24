import logging
import time
import yaml
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

HAVE_CAN_DEVICE = False

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCfgMsg, JerryCANCmdType

    HAVE_CAN_DEVICE = True
except Exception as ex:
    logger.warning("Alogus hardware support not found")
    pass

from autotrainer.core import EventManager
from .motor_steps import MotorSteps
from .device import Device
from .emulation_interface import EmulationInterface
from .device_api import DeviceApi
from .gym_device import GymDeviceMessageKind, GymDeviceEventKind
from .head_fix import HeadFixMeasurement, HeadFixMessageKind
from .pellet_delivery import PelletDeliveryMessageKind
from .can_interface import CanInterface
from .device_interface import *


class CanDevice(Device):
    """
    Somewhat temporary attempt to confirm the Alogus hardware to the existing device hardware interface.  Will likely
    change substantially.

    Generally used in combination with DeviceThread to fully communicate with the Alogus hardware.
    """

    def __init__(self, api: DeviceApi = None, buffer_size: int = 50):
        super().__init__(api)

        self._measurement_buffer_count = buffer_size

        self._measurements: typing.List[HeadFixMeasurement] = []

        self._current_measurement = None

        self._current_digital = 0
        self._current_temperature = 0
        self._current_humidity = 0

        self._pellet_dst: typing.Optional[int] = None
        self._magnet_dst: typing.Optional[int] = None

        self._interface = CanInterface() if HAVE_CAN_DEVICE else EmulationInterface()

        self._pellet_desired_x = None
        self._pellet_desired_y = None
        self._pellet_desired_z = None

        self._is_homing_x = None
        self._is_homing_y = None
        self._is_homing_z = None

        self._pellet_desired_load = None

        self._pending_move_token = None

        self._compound_movement = None

        self._home_movement = None
        self._load_movement = None
        self._send_movement = None

        self._delay_start = None
        self._delay_desired = None

        self.load_defaults()

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    def load_defaults(self):
        load_config = None
        barrier_config = None
        x_config = None
        y_config = None
        z_config = None
        magnet_config = None
        load_movement = None
        send_movement = None
        home_movement = None
        config = Path.home().joinpath(".alogus_config.yaml")
        logger.info(f"looking for configuration alogus file: {config}")

        if config.exists():
            try:
                with open(config, "r") as file:
                    conf = yaml.safe_load(file)
                    logging.info("alogus configuration loaded")
                    if "pellet" in conf:
                        if "load" in conf["pellet"]:
                            load_config = ServoConfig.from_dict(conf["pellet"]["load"])
                            logger.info(f"load configuration: {load_config}")
                        if "barrier" in conf["pellet"]:
                            barrier_config = ServoConfig.from_dict(conf["pellet"]["barrier"])
                            logger.info(f"barrier configuration: {barrier_config}")
                        if "x" in conf["pellet"]:
                            x_config = StepperConfig.from_dict(conf["pellet"]["x"])
                            logger.info(f"X stepper configuration: {x_config}")
                        if "y" in conf["pellet"]:
                            y_config = StepperConfig.from_dict(conf["pellet"]["y"])
                            logger.info(f"Y stepper configuration: {y_config}")
                        if "z" in conf["pellet"]:
                            z_config = StepperConfig.from_dict(conf["pellet"]["z"])
                            logger.info(f"Z stepper configuration: {z_config}")
                        if "head" in conf["magnet"]:
                            magnet_config = ServoConfig.from_dict(conf["magnet"]["head"])
                            logger.info(f"Magnet stepper configuration: {z_config}")
                        if "actions" in conf["pellet"]:
                            if "load" in conf["pellet"]["actions"]:
                                load_movement = MotorSteps.from_dict("load", conf["pellet"][
                                    "actions"]["load"])
                            if "home" in conf["pellet"]["actions"]:
                                home_movement = MotorSteps.from_dict("home",
                                                                     conf["pellet"]["actions"][
                                                                         "home"])
                            if "send" in conf["pellet"]["actions"]:
                                send_movement = MotorSteps.from_dict("send",
                                                                     conf["pellet"]["actions"][
                                                                         "send"])
            except Exception as e:
                logger.error(f"error loading config: {e}")

            self._home_movement = home_movement
            self._load_movement = load_movement
            self._send_movement = send_movement

            self._interface.set_motor_configuration(Motor.PELLET_LOAD_SERVO,
                                                    servo_config=load_config)
            self._interface.set_motor_configuration(Motor.PELLET_LOAD_SERVO,
                                                    servo_config=barrier_config)
            self._interface.set_motor_configuration(Motor.PELLET_LOAD_SERVO,
                                                    stepper_config=x_config)
            self._interface.set_motor_configuration(Motor.PELLET_LOAD_SERVO,
                                                    stepper_config=y_config)
            self._interface.set_motor_configuration(Motor.PELLET_LOAD_SERVO,
                                                    stepper_config=z_config)
            self._interface.set_motor_configuration(Motor.MAGNET_SERVO,
                                                    servo_config=magnet_config)

    def notify_message(self, kind: int, data: object, context: object = None) -> None:
        if self._interface is None:
            return

        if kind == GymDeviceMessageKind.VERSION:
            self._api.send_message(GymDeviceMessageKind.VERSION, "1.0")
            self._complete_command(context)

        elif kind == GymDeviceMessageKind.READ_CONFIG:
            self._interface.request_motor_config(data)

        elif kind == GymDeviceMessageKind.WRITE_CONFIG:
            if CanInterface.is_stepper(data.motor):
                self._interface.write_stepper_config(data)
            else:
                self._interface.write_servo_config(data)

            self._interface.request_motor_config(data.motor)

        elif kind == HeadFixMessageKind.UPDATE_SCALE_TARE:
            self._interface.tare_load_cell()
            self._interface.tare_pressure_sensor()
            self._complete_command(context)

        elif kind == HeadFixMessageKind.MAGNET_INTENSITY:
            self._interface.set_magnet(position=typing.cast(int, data))
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.SET_X:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            location = typing.cast(int, data) / 10.0
            self._pellet_desired_x = location
            self._interface.set_x(location)

        elif kind == PelletDeliveryMessageKind.SET_Y:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            location = typing.cast(int, data) / 10.0
            self._pellet_desired_y = location
            self._interface.set_y(location)

        elif kind == PelletDeliveryMessageKind.SET_Z:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            location = typing.cast(int, data) / 10.0
            self._pellet_desired_z = location
            self._interface.set_z(location)

        elif kind == PelletDeliveryMessageKind.SEND_TO_LIMITS:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return

            motor = typing.cast(Motor, data)
            self._interface.stepper_home(motor)
            self._pending_move_token = context

            if motor is Motor.PELLET_X_MOTOR:
                self._is_homing_x = True
            elif motor is Motor.PELLET_Y_MOTOR:
                self._is_homing_y = True
            elif motor is Motor.PELLET_Z_MOTOR:
                self._is_homing_z = True

        elif kind == PelletDeliveryMessageKind.SEND_HOME:
            if self._pending_move_token is not None or self._home_movement is None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._compound_movement = self._home_movement.steps
            logger.info(f"performing compound action: {self._compound_movement}")
            self._perform_next_compound_step()

        elif kind == PelletDeliveryMessageKind.LOAD_PELLET:
            if self._pending_move_token is not None or self._load_movement is None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._compound_movement = self._load_movement.steps
            logger.info(f"performing compound action: {self._compound_movement}")
            self._perform_next_compound_step()

        elif kind == PelletDeliveryMessageKind.SEND_PELLET:
            if self._pending_move_token is not None or self._send_movement is None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._compound_movement = self._send_movement.steps
            logger.info(f"performing compound action: {self._compound_movement}")
            self._perform_next_compound_step()

        elif kind == PelletDeliveryMessageKind.RELEASE_PELLET:
            self._interface.release_pellet()
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.COVER_PELLET:
            self._interface.cover_pellet()
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.PLAY_TONE:
            self._interface.emit_tone(data[0], data[1])
            self._complete_command(context)

        else:
            logger.info(f"unhandled command queue message: {kind}")

    def notify_data(self, data: typing.Any) -> None:
        for message in data:
            if isinstance(message, Status):
                pass

            elif isinstance(message, LoadCellReading):
                self._current_measurement = HeadFixMeasurement(time.time(),
                                                               time.perf_counter_ns(),
                                                               message.load_mv,
                                                               self._current_digital, 0,
                                                               self._current_temperature,
                                                               self._current_humidity)

            elif isinstance(message, PressureReading):
                if self._current_measurement is not None:
                    self._current_measurement.pressure = message.pressure_mv
                    self._measurements.append(self._current_measurement)
                    self._current_measurement = None

                if len(self._measurements) >= self._measurement_buffer_count:
                    self._api.send_message(HeadFixMessageKind.MEASUREMENT,
                                           self._measurements.copy())
                    self._measurements = list()

            elif isinstance(message, SensorStatus):
                self._current_temperature = message.temperature_c * (9.0 / 5) + 32
                self._current_humidity = message.humidity_percent

            elif isinstance(message, MagnetDigitalInputs):
                self._current_digital = message.continuity_0

            elif isinstance(message, StepperStatus):
                if message.motor is Motor.PELLET_X_MOTOR:
                    self._manage_next_move(PelletDeliveryMessageKind.UPDATE_X,
                                           message.position, self._pellet_desired_x)

                elif message.motor is Motor.PELLET_Y_MOTOR:
                    self._manage_next_move(PelletDeliveryMessageKind.UPDATE_Y,
                                           message.position, self._pellet_desired_y)

                elif message.motor is Motor.PELLET_Z_MOTOR:
                    self._manage_next_move(PelletDeliveryMessageKind.UPDATE_Z,
                                           message.position, self._pellet_desired_z)

                if self._pending_move_token is not None:
                    logger.debug(
                        f"[{datetime.now()}] stepper {message.motor} position: {message.position} limit switch: {message.limit_switch}")

            elif isinstance(message, ServoStatus):
                if message.motor is Motor.PELLET_LOAD_SERVO:
                    self._manage_next_move(PelletDeliveryMessageKind.UPDATE_LOAD_SERVO,
                                           message.position, self._pellet_desired_load)

                if self._pending_move_token is not None:
                    logger.debug(
                        f"[{datetime.now()}] servo {message.target.value}"
                        f":{message.motor.value} position: {message.position}")

                # @TODO Deliver the full packet, not just the value. Have the same for StepperStatus
                if self._api is not None:
                    if message.motor is Motor.MAGNET_SERVO:
                        self.api.send_message(HeadFixMessageKind.UPDATE_MAGNET, message.position)
                    elif message.motor is Motor.PELLET_LOAD_SERVO:
                        self.api.send_message(PelletDeliveryMessageKind.UPDATE_LOAD_SERVO,
                                              message.position)
                    elif message.motor is Motor.PELLET_COVER_SERVO:
                        self.api.send_message(PelletDeliveryMessageKind.UPDATE_COVER_SERVO,
                                              message.position)

            elif isinstance(message, StepperConfig):
                if self._api is not None:
                    self.api.send_message(GymDeviceMessageKind.READ_CONFIG, message)
                logger.debug(
                    f"stepper {message.target.value}|{message.motor}: {message.min_step_inverse}"
                    f" {message.steps_per_revolution}")

            elif isinstance(message, ServoConfig):
                if self._api is not None:
                    self.api.send_message(GymDeviceMessageKind.READ_CONFIG, message)
                logger.debug(
                    f"servo {message.target.value}|{message.motor.value}:"
                    f" {message.min_position} {message.min_pwm_duration_us}"
                    f" {message.max_position} {message.max_pwm_duration_us}"
                    f" {message.max_velocity} {message.max_acceleration}"
                )

        # Check for any delay requests
        if self._delay_desired is not None:
            if time.time() - self._delay_start > self._delay_desired:
                self._delay_desired = None
                logger.debug("delay end")
                self._perform_next_compound_step()

        # Breath on Linux
        time.sleep(0.001)

    def _complete_command(self, token: object) -> None:
        EventManager.post_event(GymDeviceEventKind.deviceCommandAcknowledge, context=token)
        self._api.send_message(GymDeviceMessageKind.ACK, token)

    def _manage_next_move(self, kind, position, desired):
        if self._api is not None:
            self.api.send_message(kind, position)
        if desired is not None:
            if abs(position - desired) < 0.01:
                if self._compound_movement is not None:
                    self._perform_next_compound_step()
                else:
                    token = self._pending_move_token
                    self._pending_move_token = None
                    self._complete_command(token)

    def _perform_next_compound_step(self):
        self._pellet_desired_x = None
        self._pellet_desired_y = None
        self._pellet_desired_z = None
        self._delay_desired = None
        self._pellet_desired_load = None

        if self._compound_movement is not None:
            if len(self._compound_movement) > 0:
                step = self._compound_movement.pop(0)
                if "x" in step:
                    location = step["x"] / 10.0
                    self._pellet_desired_x = location
                    self._interface.set_x(location)
                elif "y" in step:
                    location = step["y"] / 10.0
                    self._pellet_desired_y = location
                    self._interface.set_y(location)
                elif "z" in step:
                    location = step["z"] / 10.0
                    self._pellet_desired_z = location
                    self._interface.set_z(location)
                elif "load" in step:
                    location = step["load"]
                    self._pellet_desired_load = location
                    self._interface.set_load(location)
                elif "delay" in step:
                    self._delay_start = time.time()
                    self._delay_desired = step["delay"]
                    logger.debug("delay start")
            else:
                token = self._pending_move_token
                self._pending_move_token = None
                self._complete_command(token)
                self._compound_movement = None
