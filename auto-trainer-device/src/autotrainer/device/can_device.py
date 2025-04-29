"""
Device interface for the CANbus protocol to the Alogus device.

Extends the Device class that defines a fixed API to access the device. This
class relies on the CanInterface class to send and receive data.

As part of its initialization sequence, it loads a set of multi-stage motor movement
protocols from the file ~/.alogus_config.yaml.
"""

import logging
import time
from typing import Tuple, Union, SupportsInt

logger = logging.getLogger(__name__)

HAVE_CAN_DEVICE = False

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCfgMsg, JerryCANCmdType

    HAVE_CAN_DEVICE = True
except (ModuleNotFoundError, TypeError, AttributeError):
    pass

from autotrainer.core import SystemStatusMessageKind, SystemCommandKind, \
    AudioSpectrumData

from .motor_steps import MotorSteps
from .device import Device
from .emulation_interface import EmulationInterface
from .device_api import DeviceApi
from .head_fix_measurement import HeadFixMeasurement
from .can_interface import CanInterface
from .device_interface import *


class CanDevice(Device):

    def __init__(self, api: DeviceApi = None, buffer_size: int = 50, force_emulation: bool = False):
        self._interface = \
            CanInterface() if HAVE_CAN_DEVICE and not force_emulation \
                else EmulationInterface()
        super().__init__(self._interface, api)

        self._measurement_buffer_count = buffer_size
        self._measurements: typing.List[HeadFixMeasurement] = []

        self._current_pressure = 0
        self._current_digital = 0
        self._current_temperature = 0
        self._current_humidity = 0
        self._current_audio = []

        self._pellet_dst: typing.Optional[int] = None
        self._magnet_dst: typing.Optional[int] = None

        self._pending_context = None

        self._homing_motors = []

        self._load_pellet = default_load_pellet()
        self._send_pellet = default_send_pellet()
        self._cover_pellet = default_cover_pellet()
        self._release_pellet = default_release_pellet()
        self._compound_movement = None  # Current compound movement

        if not HAVE_CAN_DEVICE:
            logger.warning(
                "Alogus hardware or hardware support not found.  Using emulation interface.")

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    '''
    Start a sequence of activities
    '''

    def _start_sequence(self, movements: MotorSteps):
        if movements is None or movements.is_empty:
            self._command_complete()
        else:
            self._compound_movement = movements.steps
            self._perform_next_compound_step()

    '''
    This method is called when a command to a target is requested. This method
    translates the application command to the appropriate call to the CanInterface
    instance
    '''

    def notify_message(self, kind: int, data: Union[str, float, int, SupportsInt], context:
    object = None) -> None:
        if self._interface is None:
            return

        self._pending_context = context

        if kind == SystemCommandKind.REQUEST_VERSION:
            self._interface.request_version()

        elif kind == SystemCommandKind.READ_MOTOR_CONFIGURATION:
            assert isinstance(data, Motor)
            self._interface.request_motor_config(data)

        elif kind == SystemCommandKind.WRITE_MOTOR_CONFIGURATION:
            assert isinstance(data, Tuple)
            motor = data[0]
            config = data[1]
            assert isinstance(motor, Motor)
            assert isinstance(config, ServoConfig) or isinstance(config, StepperConfig)
            self._interface.set_motor_configuration(motor, config)

        elif kind == SystemCommandKind.SET_LOAD_PELLET_PROCEDURE:
            assert isinstance(data, MotorSteps)
            if not data.is_empty:
                logger.info(f"Setting LOAD procedure to: \n{data.steps}")
                self._load_pellet = data

        elif kind == SystemCommandKind.SET_SEND_PELLET_PROCEDURE:
            assert isinstance(data, MotorSteps)
            if not data.is_empty:
                self._send_pellet = data

        elif kind == SystemCommandKind.SET_COVER_PELLET_PROCEDURE:
            assert isinstance(data, MotorSteps)
            if not data.is_empty:
                self._cover_pellet = data

        elif kind == SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE:
            assert isinstance(data, MotorSteps)
            if not data.is_empty:
                self._release_pellet = data

        elif kind == SystemCommandKind.UPDATE_SCALE_TARE:
            self._interface.tare_load_cell()
            self._interface.tare_pressure_sensor()

        elif kind == SystemCommandKind.SET_MAGNET_INTENSITY:
            self._interface.set_magnet(int(data))

        elif kind == SystemCommandKind.SET_LOAD_SERVO:
            self._interface.set_load_servo(int(data))

        elif kind == SystemCommandKind.SET_COVER_SERVO:
            self._interface.set_cover_servo(int(data))

        elif kind == SystemCommandKind.SET_X:
            self._interface.set_x(float(data), True)

        elif kind == SystemCommandKind.SET_Y:
            self._interface.set_y(float(data), True)

        elif kind == SystemCommandKind.SET_Z:
            self._interface.set_z(float(data), True)

        elif kind == SystemCommandKind.MOVE_X:
            self._interface.set_x(float(data), False)

        elif kind == SystemCommandKind.MOVE_Y:
            self._interface.set_y(float(data), False)

        elif kind == SystemCommandKind.MOVE_Z:
            self._interface.set_z(float(data), False)

        elif kind == SystemCommandKind.SEND_TO_LIMITS:
            motor = typing.cast(Motor, data)
            self._home([motor])

        elif kind == SystemCommandKind.SEND_HOME:
            self._home([Motor.PELLET_X_MOTOR, Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR])

        elif kind == SystemCommandKind.SEND_FIXED_XYZ:
            self._interface.fixed_position()

        elif kind == SystemCommandKind.LOAD_PELLET:
            self._start_sequence(self._load_pellet)

        elif kind == SystemCommandKind.SEND_PELLET:
            self._start_sequence(self._send_pellet)

        elif kind == SystemCommandKind.RELEASE_PELLET:
            self._start_sequence(self._release_pellet)

        elif kind == SystemCommandKind.COVER_PELLET:
            self._start_sequence(self._cover_pellet)

        elif kind == SystemCommandKind.PLAY_TONE:
            assert isinstance(data, tuple)
            self._interface.emit_tone(data[0], data[1])

        elif kind == SystemCommandKind.SET_DIGITAL_OUTPUT:
            assert isinstance(data, tuple)  # channel, state
            self._interface.set_digital_output(DigitalOutputs(data[0]), data[1] != 0)

        elif kind == SystemCommandKind.SET_ANALOG_OUTPUT:
            assert isinstance(data, tuple)  # channel, voltage
            self._interface.set_analog_output(AnalogOutputs(data[0]), data[1])

        elif kind == SystemCommandKind.SET_RGB_LED:
            assert isinstance(data, tuple)
            self._interface.set_color_led(data[0], data[1], data[2])

        elif kind == SystemCommandKind.DELAY:
            self._interface.delay(data)

        elif kind == SystemCommandKind.STREAM_START or \
            kind == SystemCommandKind.STREAM_STOP:
            pass

        else:
            logger.info(f"unhandled command queue message: {kind}")

    '''
    This method is called when data from the target is received. The data is 
    forwarded to a DeviceAPI class.
    '''

    def notify_data(self, data: typing.Any) -> None:
        if self._api is None:
            return

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
                                                 self._current_humidity)

                self._measurements.append(measurement)

                if len(self._measurements) >= self._measurement_buffer_count:
                    self._api.send_message(SystemStatusMessageKind.MEASUREMENTS,
                                           self._measurements.copy())
                    self._measurements = list()

            elif isinstance(message, PressureReading):
                self._current_pressure = message.pressure

            elif isinstance(message, SensorStatus):
                self._current_temperature = message.temperature_c
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
                self.api.send_message(SystemStatusMessageKind.AUDIO_SPECTRUM,
                                      AudioSpectrumData(when_val=message.when,
                                                        index_val=message.index,
                                                        magnitudes_val=message.magnitudes))

            elif isinstance(message, StepperStatus):
                self._report_motor_status(message.motor,
                                          message.position,
                                          message.is_at_limit)

            elif isinstance(message, ServoStatus):
                self._report_motor_status(message.motor, message.position)

            elif isinstance(message, StepperConfig):
                self.api.send_message(SystemStatusMessageKind.MOTOR_CONFIGURATION, message)
                self._perform_next_compound_step()

            elif isinstance(message, ServoConfig):
                self.api.send_message(SystemStatusMessageKind.MOTOR_CONFIGURATION, message)
                self._perform_next_compound_step()

            elif isinstance(message, Version):
                self.api.send_message(SystemStatusMessageKind.FIRMWARE_VERSION, message.version)
                self._perform_next_compound_step()

            elif isinstance(message, DoorData):
                if self._api is not None:
                    self.api.send_message(SystemStatusMessageKind.FRONT_DOOR,
                                          message.open_state[0])
                    self.api.send_message(SystemStatusMessageKind.DRAWER_DOOR,
                                          message.open_state[1])

            elif isinstance(message, Acknowledge):
                if message.uuid == self._interface.uuid():
                    self._perform_next_compound_step()

        # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
        # significantly slow down the system without explicitly yielding, despite being in its own thread.  This is
        # not the case for other platforms/combinations of the above so may not be apparent when not on the
        # deployment current platform.
        time.sleep(0.001)

    '''
    On completion of a command, the class reports that to a DeviceAPI class.
    Note that 'completion' may only indicate that the message was sent to the
    target, not that the target is complete in executing the command.
    '''

    def _command_complete(self) -> None:
        super()._acknowledge_command(self._pending_context)
        self._pending_context = None

    """
    Transition a stepper motor to its home position, at the limit switch
    """

    def _home(self, motors):
        if len(motors) > 0:
            self._interface.stepper_home(motors[0])
            self._homing_motors = motors

    '''
    On a multi-step motor sequence, handle the next step of the sequence when its
    detected that the current motor movement is complete
    '''

    def _report_motor_status(self, motor, position, _at_limit: bool = False):
        if self._api is not None:
            kind = None
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
            if kind is not None:
                self.api.send_message(kind, position)

    '''
    Issue the next step in a multi-step motor sequence
    '''

    def _perform_next_compound_step(self):
        if len(self._homing_motors) > 1:
            self._homing_motors.pop(0)
            self._home(self._homing_motors)
        elif self._compound_movement is not None and \
            len(self._compound_movement) > 0:
            step = self._compound_movement.pop(0)

            if "x" in step:
                location = step["x"]
                self._interface.set_x(location)

            elif "y" in step:
                location = step["y"]
                self._interface.set_y(location)

            elif "z" in step:
                location = step["z"]
                self._interface.set_z(location)

            elif "load_arm" in step:
                location = step["load_arm"]
                self._interface.set_load_servo(location)

            elif "barrier_arm" in step:
                location = step["barrier_arm"]
                self._interface.set_cover_servo(location)

            elif "magnet" in step:
                location = step["magnet"]
                self._interface.set_magnet(location)

            elif "delay" in step:
                logger.debug("delay start")
                self._interface.delay(step["delay"])

            elif "tone" in step:
                freq, duration = step["tone"].split(',')  # (hz), (sec)
                self._interface.emit_tone(int(freq), int(float(duration) * 1000))

            elif "predefined" in step:
                predefined = step["predefined"]
                if predefined == "send":
                    self._interface.fixed_position()
                elif predefined == "cover":
                    self._interface.cover_pellet()
                elif predefined == "release":
                    self._interface.release_pellet()
                elif predefined == "retrieve":
                    self._interface.retrieve_pellet()
                elif predefined == "scoop":
                    self._interface.scoop_pellet()
                elif predefined == "home":
                    self._home([Motor.PELLET_X_MOTOR, Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR])
        else:
            self._command_complete()
            self._compound_movement = None
            self._homing_motors = []


def default_load_pellet() -> MotorSteps:
    return MotorSteps("load_pellet",
                      [
                          {'x': 0.0},
                          {'predefined': 'retrieve'},
                          {'delay': 1.0},  # in sec
                          {'z': 5.0},
                          {'predefined': 'scoop'},
                          {'delay': 1.0},
                          {'z': 0.0},  # in mm
                          {'delay': 1.0},
                      ]
                      )


def default_send_pellet() -> MotorSteps:
    return MotorSteps("send_pellet",
                      [
                          {'predefined': 'send'},
                      ]
                      )


def default_cover_pellet() -> MotorSteps:
    return MotorSteps("cover_pellet",
                      [
                          {'predefined': 'cover'},
                      ]
                      )


def default_release_pellet() -> MotorSteps:
    return MotorSteps("release_pellet",
                      [
                          {'predefined': 'release'},
                      ]
                      )
