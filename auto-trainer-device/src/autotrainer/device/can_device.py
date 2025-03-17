import logging
import time
import typing
from datetime import datetime

from .motor_steps import MotorSteps

logger = logging.getLogger(__name__)

HAVE_CAN_DEVICE = False
IS_REAL_CAN_DEVICE = False

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCfgMsg, JerryCANCmdType

    HAVE_CAN_DEVICE = True
    IS_REAL_CAN_DEVICE = True
except Exception as ex:
    logger.warning("Alogus hardware support not found")
    pass

from autotrainer.core import EventManager

from .device import Device
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

    @staticmethod
    def _as_can_interface(value) -> typing.Optional[CanInterface]:
        if value is not None and isinstance(value.interface, CanInterface):
            return value.interface
        return None

    def __init__(self, api: DeviceApi = None, buffer_size: int = 50, home_movement=None,
                 load_movement=None,
                 send_movement=None):
        super().__init__(api)

        self._measurement_buffer_count = buffer_size

        self._measurements: typing.List[HeadFixMeasurement] = []

        self._current_measurement = None

        self._current_digital = 0
        self._current_temperature = 0
        self._current_humidity = 0

        self._pellet_dst: typing.Optional[int] = None
        self._magnet_dst: typing.Optional[int] = None

        self._interface: typing.Optional[CanInterface] = api.interface if api is not None else \
            None

        self._pellet_desired_x = None
        self._pellet_desired_y = None
        self._pellet_desired_z = None

        self._pellet_desired_load = None

        self._pending_move_token = None

        self._compound_movement = None

        self._home_movement: MotorSteps = home_movement
        self._load_movement: MotorSteps = load_movement
        self._send_movement: MotorSteps = send_movement

        self._delay_start = None
        self._delay_desired = None

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

        self._interface = CanDevice._as_can_interface(value)

    def notify_message(self, kind: int, data: object, context: object = None) -> None:
        if self._interface is None:
            return

        if kind == GymDeviceMessageKind.VERSION:
            self._api.send_message(GymDeviceMessageKind.VERSION, "1.0")
            self._complete_command(context)
        elif kind == HeadFixMessageKind.UPDATE_SCALE_TARE:
            self._interface.tare_load_cell()
            self._complete_command(context)
        elif kind == HeadFixMessageKind.MAGNET_INTENSITY:
            self._interface.set_magnet(typing.cast(int, data))
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
                self._current_digital = message

            elif isinstance(message, StepperStatus):
                if message.motor is Motor.PELLET_X_MOTOR:
                    if self._api is not None:
                        self.api.send_message(PelletDeliveryMessageKind.UPDATE_X,
                                              message.position)
                    if self._pellet_desired_x is not None:
                        if abs(
                            message.position - self._pellet_desired_x) < 0.01:
                            self._pellet_desired_x = None
                            if self._compound_movement is not None:
                                self._perform_next_compound_step()
                            else:
                                token = self._pending_move_token
                                self._pending_move_token = None
                                self._complete_command(token)
                elif message.motor is Motor.PELLET_Y_MOTOR:
                    if self._api is not None:
                        self.api.send_message(PelletDeliveryMessageKind.UPDATE_Y,
                                              message.position)
                    if self._pellet_desired_y is not None:
                        if abs(
                            message.position - self._pellet_desired_y) < 0.01:
                            self._pellet_desired_y = None
                            if self._compound_movement is not None:
                                self._perform_next_compound_step()
                            else:
                                token = self._pending_move_token
                                self._pending_move_token = None
                                self._complete_command(token)
                elif message.motor is Motor.PELLET_Z_MOTOR:
                    if self._api is not None:
                        self.api.send_message(PelletDeliveryMessageKind.UPDATE_Z,
                                              message.position)
                    if self._pellet_desired_z is not None:
                        if abs(
                            message.position - self._pellet_desired_z) < 0.01:
                            self._pellet_desired_z = None
                            if self._compound_movement is not None:
                                self._perform_next_compound_step()
                            else:
                                token = self._pending_move_token
                                self._pending_move_token = None
                                self._complete_command(token)

                if self._pending_move_token is not None:
                    logger.debug(
                        f"[{datetime.now()}] stepper {message.motor} position: {message.position} limit switch: {message.limit_switch}")

            elif isinstance(message, ServoStatus):
                if message.motor is Motor.PELLET_LOAD_SERVO:
                    if self._pellet_desired_load is not None:
                        if abs(message.position - self._pellet_desired_load) < 0.5:
                            self._pellet_desired_load = None
                            if self._compound_movement is not None:
                                self._perform_next_compound_step()
                            else:
                                token = self._pending_move_token
                                self._pending_move_token = None
                                self._complete_command(token)

                if self._pending_move_token is not None:
                    logger.debug(
                        f"[{datetime.now()}] servo {message.target.value}"
                        f":{message.motor.value} position: {message.position}")

            elif isinstance(message, StepperConfig):
                logger.debug(
                    f"stepper {message.target.value}|{message.motor}: {message.min_step_inverse}"
                    f" {message.steps_per_revolution}")

            elif isinstance(message, ServoConfig):
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

    def _perform_next_compound_step(self):
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

    @staticmethod
    def _create_home_movement(self):
        return [
            {"z": 10.5},
            {"x": 20.5},
            {"y": 30.5}
        ]

    @staticmethod
    def _create_send_movement(self):
        return [
            {"z": 20.5},
            {"x": 10.5},
            {"y": 30.5},
        ]

    @staticmethod
    def _create_load_movement(self):
        return [
            {"z": 30.5},
            {"x": 20.5},
            {"y": 10.5},
            {"load": 100},
            {"z": 20.5},
            {"load": 0},
        ]
