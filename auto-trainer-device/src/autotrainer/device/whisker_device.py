import logging
import time
import typing
from datetime import datetime

from .motor_steps import MotorSteps

logger = logging.getLogger(__name__)

HAVE_WHISKER_DEVICE = False
IS_REAL_WHISKER_DEVICE = False

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCfgMsg, JerryCANCmdType

    HAVE_WHISKER_DEVICE = True
    IS_REAL_WHISKER_DEVICE = True
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

PELLET_DESTINATION = 0x00
MAGNET_DESTINATION = 0x01


class WhiskerDevice(Device):
    """
    Somewhat temporary attempt to confirm the Alogus hardware to the existing device hardware interface.  Will likely
    change substantially.

    Generally used in combination with DeviceThread to fully communicate with the Alogus hardware.
    """

    @staticmethod
    def _as_whisker_interface(value) -> typing.Optional[CanInterface]:
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

        self._whisker_interface: typing.Optional[CanInterface] = None

        self._pellet_desired_x = None
        self._pellet_desired_y = None
        self._pellet_desired_z = None

        self._pellet_desired_load = None

        self._pending_move_token = None

        self._compound_movement = None

        self._home_movement: WhiskerMovement = home_movement
        self._load_movement: WhiskerMovement = load_movement
        self._send_movement: WhiskerMovement = send_movement

        self._delay_start = None
        self._delay_desired = None

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

        self._whisker_interface = WhiskerDevice._as_whisker_interface(value)

        if self._whisker_interface is not None:
            logger.info("whisker interface set")

            if self._pellet_dst is not None:
                self._whisker_interface.configure_pellet(self._pellet_dst)

            if self._magnet_dst is not None:
                self._whisker_interface.configure_magnet(self._magnet_dst)

    def notify_message(self, kind: int, data: object, context: object = None) -> None:
        if self._whisker_interface is None:
            return

        if kind == GymDeviceMessageKind.VERSION:
            self._api.send_message(GymDeviceMessageKind.VERSION, "1.0")
            self._complete_command(context)
        elif kind == HeadFixMessageKind.UPDATE_SCALE_TARE:
            self._whisker_interface.tare_load_cell()
            self._complete_command(context)
        elif kind == HeadFixMessageKind.MAGNET_INTENSITY:
            self._whisker_interface.set_magnet(self._magnet_dst, typing.cast(int, data))
            self._complete_command(context)
        elif kind == PelletDeliveryMessageKind.SET_X:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            location = typing.cast(int, data) / 10.0
            self._pellet_desired_x = location
            self._whisker_interface.set_x(location)
        elif kind == PelletDeliveryMessageKind.SET_Y:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            location = typing.cast(int, data) / 10.0
            self._pellet_desired_y = location
            self._whisker_interface.set_y(location)
        elif kind == PelletDeliveryMessageKind.SET_Z:
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            location = typing.cast(int, data) / 10.0
            self._pellet_desired_z = location
            self._whisker_interface.set_z(location)
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
            self._whisker_interface.release_pellet()
            self._complete_command(context)
        elif kind == PelletDeliveryMessageKind.COVER_PELLET:
            self._whisker_interface.cover_pellet()
            self._complete_command(context)
        else:
            logger.info(f"unhandled command queue message: {kind}")

    def notify_data(self, data: typing.Any) -> None:
        for message in data:
            if isinstance(message, JerryCANMsg):
                if self._pellet_dst is None:
                    if message.dst_id >> 2 == PELLET_DESTINATION:
                        self._pellet_dst = message.dst_id
                        logger.info(f"pellet module located at {self._pellet_dst}")
                        self._whisker_interface.configure_pellet(self._pellet_dst)

                if self._magnet_dst is None:
                    if message.dst_id >> 2 == MAGNET_DESTINATION:
                        self._magnet_dst = message.dst_id
                        logger.info(f"magnet module located at {self._magnet_dst}")
                        self._whisker_interface.configure_magnet(self._magnet_dst)

                if message.type == JerryCANCmdType.STATUS:
                    pass
                elif message.type == JerryCANCmdType.LOAD_CELL_READ:
                    self._current_measurement = HeadFixMeasurement(time.time(),
                                                                   time.perf_counter_ns(),
                                                                   message.load_cell_read.load_mv * 10,
                                                                   self._current_digital, 0,
                                                                   self._current_temperature,
                                                                   self._current_humidity)
                elif message.type == JerryCANCmdType.PRESSURE_READ:
                    if self._current_measurement is not None:
                        self._current_measurement.pressure = message.pressure_read.pressure_mv
                        self._measurements.append(self._current_measurement)
                        self._current_measurement = None

                    if len(self._measurements) >= self._measurement_buffer_count:
                        self._api.send_message(HeadFixMessageKind.MEASUREMENT,
                                               self._measurements.copy())
                        self._measurements = list()
                elif message.type == JerryCANCmdType.TEMP_HUM_READ:
                    self._current_temperature = (message.temp_hum_read.temperature / 100.0) * (
                        9.0 / 5) + 32
                    self._current_humidity = message.temp_hum_read.humidity / 100.0
                elif message.type == JerryCANCmdType.GPIO_READ:
                    if message.dst_id == self._magnet_dst:
                        self._current_digital = (message.gpio_read.state >> 0) & 0b1
                        if self._current_digital > 1 or self._current_digital < 0:
                            logger.error(f"what?: {self._current_digital}")
                elif message.type == JerryCANCmdType.STEPPER_STATUS:
                    if message.dst_id == self._pellet_dst:
                        if message.stepper_status.motor_id == 0:
                            if self._api is not None:
                                self.api.send_message(PelletDeliveryMessageKind.UPDATE_X,
                                                      message.stepper_status.position)
                            if self._pellet_desired_x is not None:
                                if abs(
                                    message.stepper_status.position - self._pellet_desired_x) < 0.01:
                                    self._pellet_desired_x = None
                                    if self._compound_movement is not None:
                                        self._perform_next_compound_step()
                                    else:
                                        token = self._pending_move_token
                                        self._pending_move_token = None
                                        self._complete_command(token)
                        elif message.stepper_status.motor_id == 1:
                            if self._api is not None:
                                self.api.send_message(PelletDeliveryMessageKind.UPDATE_Y,
                                                      message.stepper_status.position)
                            if self._pellet_desired_y is not None:
                                if abs(
                                    message.stepper_status.position - self._pellet_desired_y) < 0.01:
                                    self._pellet_desired_y = None
                                    if self._compound_movement is not None:
                                        self._perform_next_compound_step()
                                    else:
                                        token = self._pending_move_token
                                        self._pending_move_token = None
                                        self._complete_command(token)
                        elif message.stepper_status.motor_id == 2:
                            if self._api is not None:
                                self.api.send_message(PelletDeliveryMessageKind.UPDATE_Z,
                                                      message.stepper_status.position)
                            if self._pellet_desired_z is not None:
                                if abs(
                                    message.stepper_status.position - self._pellet_desired_z) < 0.01:
                                    self._pellet_desired_z = None
                                    if self._compound_movement is not None:
                                        self._perform_next_compound_step()
                                    else:
                                        token = self._pending_move_token
                                        self._pending_move_token = None
                                        self._complete_command(token)

                        if self._pending_move_token is not None:
                            logger.debug(
                                f"[{datetime.now()}] stepper {message.stepper_status.motor_id} position: {message.stepper_status.position} status: {message.stepper_status.status} homing status: {message.stepper_status.homing_status} limit switch: {message.stepper_status.limit_switch}")
                elif message.type == JerryCANCmdType.SERVO_STATUS:
                    if message.servo_status.motor_id == 1:
                        if self._pellet_desired_load is not None:
                            if abs(message.servo_status.position - self._pellet_desired_load) < 0.5:
                                self._pellet_desired_load = None
                                if self._compound_movement is not None:
                                    self._perform_next_compound_step()
                                else:
                                    token = self._pending_move_token
                                    self._pending_move_token = None
                                    self._complete_command(token)

                    if self._pending_move_token is not None:
                        logger.debug(
                            f"[{datetime.now()}] servo {message.dst_id}:{message.servo_status.motor_id} position: {message.servo_status.position}")
                elif message.type == JerryCANCmdType.CFG_RESPONSE:
                    if message.cfg_response.type == JerryCANCfgMsg.Type.STEPPER:
                        logger.debug(
                            f"stepper {message.cfg_response.stepper.dst_id}|{message.cfg_response.stepper.motor_id}: {message.cfg_response.stepper.min_step_inverse} {message.cfg_response.stepper.steps_per_revolution}")
                    elif message.cfg_response.type == JerryCANCfgMsg.Type.SERVO:
                        logger.debug(
                            f"servo {message.cfg_response.stepper.dst_id}|{message.cfg_response.stepper.motor_id}: {message.cfg_response.stepper.min_step_inverse} {message.cfg_response.stepper.steps_per_revolution}")

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
                    self._whisker_interface.set_x(location)
                elif "y" in step:
                    location = step["y"] / 10.0
                    self._pellet_desired_y = location
                    self._whisker_interface.set_y(location)
                elif "z" in step:
                    location = step["z"] / 10.0
                    self._pellet_desired_z = location
                    self._whisker_interface.set_z(location)
                elif "load" in step:
                    location = step["load"]
                    self._pellet_desired_load = location
                    self._whisker_interface.set_load(location)
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
