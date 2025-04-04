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

        self._current_pressure = 0
        self._current_digital = 0
        self._current_temperature = 0
        self._current_humidity = 0
        self._current_audio = []

        self._pellet_dst: typing.Optional[int] = None
        self._magnet_dst: typing.Optional[int] = None

        self._interface = CanInterface() if HAVE_CAN_DEVICE else EmulationInterface()

        self._desired_location = None
        self._active_motor = None
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

    '''
    This method is called when a command to a target is requested. This method
    translates the application command to the appropriate call to the CanInterface
    instance
    '''

    def notify_message(self, kind: int, data: object, context: object = None) -> None:
        if self._interface is None:
            return

        if kind == GymDeviceMessageKind.VERSION:
            self._interface.request_version()
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
            self._move_motor(Motor.MAGNET_SERVO, data, context, self._interface.set_magnet)

        elif kind == PelletDeliveryMessageKind.SET_LOAD_SERVO:
            self._move_motor(Motor.PELLET_LOAD_SERVO, data, context, self._interface.set_load)

        elif kind == PelletDeliveryMessageKind.SET_COVER_SERVO:
            self._move_motor(Motor.PELLET_COVER_SERVO, data, context, self._interface.set_cover)

        elif kind == PelletDeliveryMessageKind.SET_X:
            self._move_motor(Motor.PELLET_X_MOTOR, data, context, self._interface.set_x)

        elif kind == PelletDeliveryMessageKind.SET_Y:
            self._move_motor(Motor.PELLET_Y_MOTOR, data, context, self._interface.set_y)

        elif kind == PelletDeliveryMessageKind.SET_Z:
            self._move_motor(Motor.PELLET_Z_MOTOR, data, context, self._interface.set_z)

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
            self._move_motor(Motor.PELLET_COVER_SERVO,
                             self._interface.cover_config.minimum_position, context,
                             self._interface.set_cover)
            self._interface.emit_tone(2000, 6000)

        elif kind == PelletDeliveryMessageKind.COVER_PELLET:
            self._move_motor(Motor.PELLET_COVER_SERVO,
                             self._interface.cover_config.maximum_position, context,
                             self._interface.set_cover)

        elif kind == PelletDeliveryMessageKind.PLAY_TONE:
            assert isinstance(data, tuple)
            self._interface.emit_tone(data[0], data[1])
            self._complete_command(context)

        elif kind == GymDeviceMessageKind.SET_DIGITAL_OUTPUT:
            assert isinstance(data, tuple)  # channel, state
            self._interface.set_digital_output(DigitalOutputs(data[0]), data[1] != 0)
            self._complete_command(context)

        elif kind == GymDeviceMessageKind.SET_ANALOG_OUTPUT:
            assert isinstance(data, tuple)  # channel, voltage
            self._interface.set_analog_output(AnalogOutputs(data[0]), data[1])
            self._complete_command(context)

        elif kind == GymDeviceMessageKind.SET_RGB_LED:
            assert isinstance(data, tuple)
            self._interface.set_color_led(data[0], data[1], data[2])
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
                measurement = HeadFixMeasurement(time.time(),
                                                 time.perf_counter_ns(),
                                                 message.load,
                                                 self._current_digital,
                                                 self._current_pressure,
                                                 self._current_temperature,
                                                 self._current_humidity,
                                                 self._current_audio)

                self._measurements.append(measurement)

                if len(self._measurements) >= self._measurement_buffer_count:
                    self._api.send_message(SystemStatusMessageKind.MEASUREMENTS,
                                           self._measurements.copy())
                    self._measurements = list()

            elif isinstance(message, PressureReading):
                self._current_pressure = message.pressure

            elif isinstance(message, SensorStatus):
                self._current_temperature = message.temperature_c * (9.0 / 5) + 32
                self._current_humidity = message.humidity_percent

            elif isinstance(message, MagnetDigitalInputs):
                self._current_digital = message.continuity_0

            elif isinstance(message, PelletDigitalInputs):
                if self._api is not None:
                    self.api.send_message(SystemStatusMessageKind.STIMULUS_INPUTS,
                                          [message.stimulus_1,
                                           message.stimulus_2,
                                           message.stimulus_3,
                                           message.stimulus_4]
                                          )

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

            elif isinstance(message, Version):
                if self._api is not None:
                    self.api.send_message(SystemStatusMessageKind.FIRMWARE_VERSION, message.version)

            elif isinstance(message, DoorData):
                if self._api is not None:
                    self.api.send_message(SystemStatusMessageKind.FRONT_DOOR,
                                          message.open_state[0])
                    self.api.send_message(SystemStatusMessageKind.DRAWER_DOOR,
                                          message.open_state[1])

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
        self._pending_move_token = None

    """
    Transition a stepper motor to its home position, at the limit switch
    """

    def _home(self, motors, context):
        if len(motors) == 0:
            self._complete_command(context)
        else:
            self._interface.stepper_home(motors[0])
            self._pending_move_token = context
            self._homing_motors = motors

    def _move_motor(self, motor: Motor, location, context, method):
        # The location is either a position or a (position, rate) pair
        if isinstance(location, float) or isinstance(location, int):
            position = location
        else:
            position = location[0]

        if self._desired_location is not None:
            self._complete_command(context)
        else:
            self._pending_move_token = context
            self._desired_location = float(position)
            self._active_motor = motor
            method(location)

            logger.debug(
                f"[{datetime.now()}]"
                f" motor: {motor_to_str(self._active_motor)}"
                f" desired: {self._desired_location}"
                f" token: {self._pending_move_token}")

    '''
    On a multi-step motor sequence, handle the next step of the sequence when its
    detected that the current motor movement is complete
    '''

    def _manage_next_move(self, motor, position, at_limit: bool = False):
        if self._api is not None:
            kind = SystemStatusMessageKind.ACK
            if motor is Motor.PELLET_X_MOTOR:
                kind = SystemStatusMessageKind.PELLET_X
            elif motor is Motor.PELLET_Y_MOTOR:
                kind = SystemStatusMessageKind.PELLET_Y
            elif motor is Motor.PELLET_Z_MOTOR:
                kind = SystemStatusMessageKind.PELLET_Z
            elif motor is Motor.PELLET_LOAD_SERVO:
                kind = SystemStatusMessageKind.PELLET_LOAD
            elif motor is Motor.PELLET_COVER_SERVO:
                kind = SystemStatusMessageKind.PELLET_COVER
            elif motor is Motor.MAGNET_SERVO:
                kind = SystemStatusMessageKind.HEAD_MAGNET

            self.api.send_message(kind, position)
        # print(f"desired={self._desired_location}/{position} motor="
        #       f"{self._active_motor}/{motor}")
        if self._desired_location is not None and \
            motor == self._active_motor and \
            abs(position - self._desired_location) < 0.01:
            if self._compound_movement is not None:
                self._perform_next_compound_step()
            else:
                self._desired_location = None
                self._active_motor = None
                self._complete_command(self._pending_move_token)

        if self._desired_location is not None and \
            motor == self._active_motor and \
            self._pending_move_token is not None:
            logger.debug(
                f"[{datetime.now()}] "
                f"motor: {motor_to_str(motor)} "
                f"position: {position} "
                f"desired: {self._desired_location}"
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

                logger.debug(f"Next step: {step}")
                if "x" in step:
                    location = step["x"]
                    self._move_motor(Motor.PELLET_X_MOTOR, location, self._pending_move_token,
                                     self._interface.set_x)

                elif "y" in step:
                    location = step["y"]
                    self._move_motor(Motor.PELLET_Y_MOTOR, location, self._pending_move_token,
                                     self._interface.set_y)

                elif "z" in step:
                    location = step["z"]
                    self._move_motor(Motor.PELLET_Z_MOTOR, location, self._pending_move_token,
                                     self._interface.set_z)

                elif "load" in step:
                    location = step["load"]
                    self._move_motor(Motor.PELLET_LOAD_SERVO, location, self._pending_move_token,
                                     self._interface.set_load)

                elif "cover" in step:
                    location = step["cover"]
                    self._move_motor(Motor.PELLET_COVER_SERVO, location, self._pending_move_token,
                                     self._interface.set_cover)

                elif "magnet" in step:
                    location = step["magnet"]
                    self._move_motor(Motor.MAGNET_SERVO, location, self._pending_move_token,
                                     self._interface.set_magnet)

                elif "delay" in step:
                    self._delay_start = time.time()
                    self._delay_period = step["delay"]
                    logger.debug("delay start")
            else:
                logger.debug("sequence complete")
                self._compound_movement = None
                self._complete_command(self._pending_move_token)


def default_load_procedure() -> MotorSteps:
    return MotorSteps("load",
                      [
                          {'load': 100},
                          {'delay': 1.0},
                          {'z': 12.2},  # in mm
                          {'load': 0.0},
                          {'delay': 1.0},
                          {'z': 0.0},  # in mm
                          {'delay': 1.0},
                      ]
                      )


def default_send_procedure() -> MotorSteps:
    return MotorSteps("send",
                      [
                          {'z': 1.22},  # in mm
                          {'x': 3.9},  # in mm
                          {'y': 4.88}  # in mm
                      ]
                      )
