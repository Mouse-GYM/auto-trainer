"""
Device interface for the CANbus protocol to the Alogus device.

Extends the Device class that defines a fixed API to access the device. This
class relies on the CanInterface class to send and receive data.

As part of its initialization sequence, it loads a set of multi-stage motor movement
protocols from the file ~/.alogus_config.yaml.
"""

import logging
import time
from datetime import datetime
from typing import Tuple

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
from .can_interface import CanInterface, motor_to_str
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

        self._desired_location = None
        self._pending_move_token = None

        self._homing_motors = []

        self._load_movement = default_load_procedure()
        self._send_movement = default_send_procedure()
        self._compound_movement = None  # Current compound movement

        self._delay_start = None
        self._delay_period = None

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    """
    Transition a stepper motor to its home position, at the limit switch
    """

    def _home(self, motors, context):
        if len(motors) == 0:
            self._complete_command(context)
            self._pending_move_token = None
        else:
            self._interface.stepper_home(motors[0])
            self._pending_move_token = context
            self._homing_motors = motors

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

        elif kind == GymDeviceMessageKind.READ_CONFIG:
            assert isinstance(data, Motor)
            self._interface.request_motor_config(data)

        elif kind == GymDeviceMessageKind.WRITE_CONFIG:
            assert isinstance(data, Tuple)
            motor = data[0]
            config = data[1]
            assert isinstance(motor, Motor)
            assert isinstance(config, ServoConfig) or isinstance(config, StepperConfig)
            self._interface.set_motor_configuration(motor, config)

        elif kind == GymDeviceMessageKind.SET_LOAD_PROCEDURE:
            assert isinstance(data, MotorSteps)
            logger.info(f"Setting LOAD procedure to: \n{data.steps}")
            self._load_movement = data

        elif kind == GymDeviceMessageKind.SET_SEND_PROCEDURE:
            assert isinstance(data, MotorSteps)
            logger.info(f"Setting SEND procedure to: \n{data.steps}")
            self._send_movement = data

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
            self._interface.set_cover(float(data))
            self._complete_command(context)

        elif kind == PelletDeliveryMessageKind.SET_X:
            assert isinstance(data, float) or isinstance(data, int)
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._desired_location = float(data)
            self._interface.set_x(self._desired_location)

        elif kind == PelletDeliveryMessageKind.SET_Y:
            assert isinstance(data, float) or isinstance(data, int)
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._desired_location = float(data)
            self._interface.set_y(self._desired_location)

        elif kind == PelletDeliveryMessageKind.SET_Z:
            assert isinstance(data, float) or isinstance(data, int)
            if self._pending_move_token is not None:
                self._complete_command(context)
                return
            self._pending_move_token = context
            self._desired_location = float(data)
            self._interface.set_z(self._desired_location)

        elif kind == PelletDeliveryMessageKind.SEND_TO_LIMITS:
            motor = typing.cast(Motor, data)
            self._home([motor], context)

        elif kind == PelletDeliveryMessageKind.SEND_HOME:
            self._home([Motor.PELLET_X_MOTOR, Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR],
                       context)

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
                self._manage_next_move(message.motor,
                                       message.position,
                                       message.is_at_limit)

            elif isinstance(message, ServoStatus):
                self._manage_next_move(message.motor, message.position)

            elif isinstance(message, StepperConfig):
                if self._api is not None:
                    self.api.send_message(GymDeviceMessageKind.READ_CONFIG, message)

            elif isinstance(message, ServoConfig):
                if self._api is not None:
                    self.api.send_message(GymDeviceMessageKind.READ_CONFIG, message)

        # Check for any delay requests
        if self._delay_period is not None:
            if time.time() - self._delay_start > self._delay_period:
                self._delay_period = None
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

    def _manage_next_move(self, motor, position, at_limit: bool = False):
        if self._api is not None:
            msg_type = SystemStatusMessageKind.ACK
            if motor is Motor.PELLET_X_MOTOR:
                msg_type = SystemStatusMessageKind.PELLET_X
            elif motor is Motor.PELLET_Y_MOTOR:
                msg_type = SystemStatusMessageKind.PELLET_Y
            elif motor is Motor.PELLET_Z_MOTOR:
                msg_type = SystemStatusMessageKind.PELLET_Z
            elif motor is Motor.PELLET_LOAD_SERVO:
                msg_type = SystemStatusMessageKind.PELLET_LOAD
            elif motor is Motor.PELLET_COVER_SERVO:
                msg_type = SystemStatusMessageKind.PELLET_COVER
            elif motor is Motor.MAGNET_SERVO:
                msg_type = SystemStatusMessageKind.HEAD_MAGNET

            self.api.send_message(msg_type, position)

        if self._desired_location is not None and \
            abs(position - self._desired_location) < 0.01:
            if self._compound_movement is not None:
                self._perform_next_compound_step()
            else:
                token = self._pending_move_token
                self._pending_move_token = None
                self._complete_command(token)

            if self._pending_move_token is not None:
                logger.debug(
                    f"[{datetime.now()}] "
                    f"motor: {motor_to_str(motor)} "
                    f"position: {position}"
                    f"limit switch: {at_limit}")


        elif len(self._homing_motors) > 0 and self._homing_motors[0] == motor and at_limit:
            self._homing_motors.pop(0)
            self._home(self._homing_motors, self._pending_move_token)

    '''
    Issue the next step in a multi-step motor sequence
    '''

    def _perform_next_compound_step(self):
        self._desired_location = None
        self._delay_period = None

        if self._compound_movement is not None:
            if len(self._compound_movement) > 0:
                step = self._compound_movement.pop(0)
                if "x" in step:
                    location = step["x"]
                    self._desired_location = location
                    self._interface.set_x(location)
                elif "y" in step:
                    location = step["y"]
                    self._desired_location = location
                    self._interface.set_y(location)
                elif "z" in step:
                    location = step["z"]
                    self._desired_location = location
                    self._interface.set_z(location)
                elif "load" in step:
                    location = step["load"]
                    self._desired_location = location
                    self._interface.set_load(location)
                elif "delay" in step:
                    self._delay_start = time.time()
                    self._delay_period = step["delay"]
                    logger.debug("delay start")
            else:
                token = self._pending_move_token
                self._pending_move_token = None
                self._complete_command(token)
                self._compound_movement = None


def default_load_procedure() -> MotorSteps:
    return MotorSteps("load",
                      [
                          {'load': 100},
                          {'delay': 1.0},
                          {'z': 5.0},
                          {'load': 0.0},
                          {'delay': 1.0},
                          {'z': 0.0},
                          {'delay': 1.0},
                      ]
                      )


def default_send_procedure() -> MotorSteps:
    return MotorSteps("send",
                      [
                          {'z': 0.5},
                          {'x': 1.6},
                          {'y': 2.0}
                      ]
                      )
