"""
Device interface for the CANbus protocol to the Alogus device.

Extends the Device class that defines a fixed API to access the device. This
class relies on the CanInterface class to send and receive data.

As part of its initialization sequence, it loads a set of multi-stage motor movement
protocols from the file ~/.alogus_config.yaml.
"""

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
except (ModuleNotFoundError, TypeError, AttributeError):
    logger.warning("Alogus hardware support not found")
    pass

from autotrainer.core import EventManager
from autotrainer.core.message import SystemStatusMessageKind
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

    def __init__(self, api: DeviceApi = None, buffer_size: int = 50):
        super().__init__(api)

        self._measurement_buffer_count = buffer_size

        self._measurements: typing.List[HeadFixMeasurement] = []

        self._current_measurement = None

        self._current_digital = 0
        self._current_temperature = 0
        self._current_humidity = 0
        self._current_audio = []

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

        config = Path.home().joinpath(".alogus_config.yaml")
        self._load_config_file(config)  # should be last line in __init__()

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    '''
    Load the default configurations and motor control sequences from ~/.alogus_config.yaml
    '''

    def _load_config_file(self, config_file):
        if isinstance(config_file, str):
            config_file = Path(config_file)

        logger.info(f"Loading Alogus configuration file: {config_file}")

        magnet_config = None
        load_config = None
        barrier_config = None
        x_config = None
        y_config = None
        z_config = None

        if config_file.exists():
            try:
                with open(config_file, "r") as file:
                    conf = yaml.safe_load(file)
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
                    if "magnet" in conf:
                        if "head" in conf["magnet"]:
                            magnet_config = ServoConfig.from_dict(conf["magnet"]["head"])
                            logger.info(f"Magnet stepper configuration: {magnet_config}")
                    if "actions" in conf:
                        if "load" in conf["actions"]:
                            self._load_movement = MotorSteps.from_dict("load",
                                                                       conf["actions"]["load"])
                        if "home" in conf["actions"]:
                            self._home_movement = MotorSteps.from_dict("home",
                                                                       conf["actions"]["home"])
                        if "send" in conf["actions"]:
                            self._send_movement = MotorSteps.from_dict("send",
                                                                       conf["actions"]["send"])
            except Exception as e:
                logger.error(f"error loading config: {e}")
                assert False

            logging.info("Alogus configuration loaded")

            self._interface.load_config = load_config
            self._interface.barrier_config = barrier_config
            self._interface.x_config = x_config
            self._interface.y_config = y_config
            self._interface.z_config = z_config
            self._interface.magnet_config = magnet_config

    '''
    This method is called when a command to a target is requested. This method
    translates the application command to the appropriate call to the CanInterface
    instance
    '''

    def notify_message(self, kind: int, data: object, context: object = None) -> None:
        if self._interface is None:
            return

        if kind == GymDeviceMessageKind.VERSION:
            self._api.send_message(GymDeviceMessageKind.VERSION, "1.0")
            self._complete_command(context)

        elif kind == GymDeviceMessageKind.LOAD_CONFIG_FILE:
            self._load_config_file(data)
            self._interface.configure_pellet()
            self._interface.configure_magnet()

        elif kind == GymDeviceMessageKind.READ_CONFIG:
            assert isinstance(data, Motor)
            self._interface.request_motor_config(data)

        elif kind == GymDeviceMessageKind.WRITE_CONFIG:
            assert isinstance(data, ServoConfig) or isinstance(data, StepperConfig)
            self._interface.set_motor_configuration(data.motor, data)
            self._interface.request_motor_config(data.motor)

        elif kind == HeadFixMessageKind.UPDATE_SCALE_TARE:
            self._interface.tare_load_cell()
            self._interface.tare_pressure_sensor()
            self._complete_command(context)

        elif kind == HeadFixMessageKind.SET_MAGNET_INTENSITY:
            assert isinstance(data, float) or isinstance(data, int)
            self._interface.set_magnet(float(data))
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.SET_LOAD_SERVO:
            assert isinstance(data, float) or isinstance(data, int)
            self._interface.set_load(float(data))
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.SET_COVER_SERVO:
            assert isinstance(data, float) or isinstance(data, int)
            self._interface.set_barrier(float(data))
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.SET_X:
            assert isinstance(data, float) or isinstance(data, int)
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._pellet_desired_x = float(data)
            self._interface.set_x(self._pellet_desired_x)

        elif kind == PelletDeliveryMessageKind.SET_Y:
            assert isinstance(data, float) or isinstance(data, int)
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._pellet_desired_y = float(data)
            self._interface.set_y(self._pellet_desired_y)

        elif kind == PelletDeliveryMessageKind.SET_Z:
            assert isinstance(data, float) or isinstance(data, int)
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._pellet_desired_z = float(data)
            self._interface.set_z(self._pellet_desired_z)

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
            assert isinstance(data, tuple)
            self._interface.emit_tone(data[0], data[1])
            self._complete_command(context)

        elif kind == HeadFixMessageKind.STREAM_START or \
            kind == HeadFixMessageKind.STREAM_STOP:
            pass

        else:
            logger.info(f"unhandled command queue message: {kind}")

    '''
    This method is called when data from the target is received. The data is 
    forwarded to a DeviceAPI class.
    '''

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
                                                               self._current_humidity,
                                                               self._current_audio)

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

            elif isinstance(message, AudioData):
                self._current_audio = message.magnitudes

            elif isinstance(message, StepperStatus):
                if message.motor is Motor.PELLET_X_MOTOR:
                    self._manage_next_move(SystemStatusMessageKind.PELLET_X,
                                           message.position, self._pellet_desired_x)

                elif message.motor is Motor.PELLET_Y_MOTOR:
                    self._manage_next_move(SystemStatusMessageKind.PELLET_Y,
                                           message.position, self._pellet_desired_y)

                elif message.motor is Motor.PELLET_Z_MOTOR:
                    self._manage_next_move(SystemStatusMessageKind.PELLET_Z,
                                           message.position, self._pellet_desired_z)

                if self._pending_move_token is not None:
                    logger.debug(
                        f"[{datetime.now()}] stepper {message.motor} position: {message.position} limit switch: {message.limit_switch}")

            elif isinstance(message, ServoStatus):
                if message.motor is Motor.PELLET_LOAD_SERVO:
                    self._manage_next_move(SystemStatusMessageKind.PELLET_LOAD,
                                           message.position, self._pellet_desired_load)

                elif message.motor is Motor.MAGNET_SERVO:
                    if self._api is not None:
                        self.api.send_message(SystemStatusMessageKind.HEAD_MAGNET, message.position)

                elif message.motor is Motor.PELLET_COVER_SERVO:
                    if self._api is not None:
                        self.api.send_message(SystemStatusMessageKind.PELLET_COVER,
                                              message.position)

                if self._pending_move_token is not None:
                    logger.debug(
                        f"[{datetime.now()}] servo {message.target.value}"
                        f":{message.motor.value} position: {message.position}")

            elif isinstance(message, StepperConfig):
                self.add_vel_and_accel_to_config(message)

                if self._api is not None:
                    self.api.send_message(GymDeviceMessageKind.READ_CONFIG, message)
                logger.debug(
                    f"stepper {message.target.value}|{message.motor}: {message.min_step_inverse}"
                    f" {message.steps_per_revolution}")

            elif isinstance(message, ServoConfig):
                self.add_vel_and_accel_to_config(message)

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

    '''
    On completion of a command, the class reports that to a DeviceAPI class.
    Note that 'completion' may only indicate that the message was sent to the
    target, not that the target is complete in executing the command.
    '''

    def _complete_command(self, token: object) -> None:
        EventManager.post_event(GymDeviceEventKind.deviceCommandAcknowledge, context=token)
        self._api.send_message(GymDeviceMessageKind.ACK, token)

    '''
    On a multi-step motor sequence, handle the next step of the sequence when its
    detected that the current motor movement is complete
    '''

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

    '''
    Issue the next step in a multi-step motor sequence
    '''

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
                    location = step["x"]
                    self._pellet_desired_x = location
                    self._interface.set_x(location)
                elif "y" in step:
                    location = step["y"]
                    self._pellet_desired_y = location
                    self._interface.set_y(location)
                elif "z" in step:
                    location = step["z"]
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

    '''
    Max velocity and acceleration was not intended to be a global configuration
    item, so it's not stored remotely. When receiving the data, the local system
    needs to update the received configuration with those values.
    '''

    def add_vel_and_accel_to_config(self, config):
        if config.motor is Motor.MAGNET_SERVO:
            config.max_velocity = self._interface.magnet_config.max_velocity
            config.max_acceleration = self._interface.magnet_config.max_acceleration

        elif config.motor is Motor.PELLET_COVER_SERVO:
            config.max_velocity = self._interface.barrier_config.max_velocity
            config.max_acceleration = self._interface.barrier_config.max_acceleration

        elif config.motor is Motor.PELLET_LOAD_SERVO:
            config.max_velocity = self._interface.load_config.max_velocity
            config.max_acceleration = self._interface.load_config.max_acceleration

        elif config.motor is Motor.PELLET_X_MOTOR:
            config.max_velocity = self._interface.x_config.max_velocity
            config.max_acceleration = self._interface.x_config.max_acceleration

        elif config.motor is Motor.PELLET_Y_MOTOR:
            config.max_velocity = self._interface.y_config.max_velocity
            config.max_acceleration = self._interface.y_config.max_acceleration

        elif config.motor is Motor.PELLET_Z_MOTOR:
            config.max_velocity = self._interface.z_config.max_velocity
            config.max_acceleration = self._interface.z_config.max_acceleration
