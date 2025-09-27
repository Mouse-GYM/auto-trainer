"""
Device interface for the CANbus protocol to the Alogus device.

Extends the Device class that defines a fixed API to access the device. This
class relies on the CanInterface class to send and receive data.

"""

import logging
import queue
import threading
import time
from functools import partial
from typing import Tuple, Union, SupportsInt, List, Optional, Any, cast

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.message import SystemDataArgsKwargs

logger = get_verbose_logger(__name__)

try:
    from pyjerrycan import JerryCAN, JerryCANMsg, JerryCANCfgMsg, JerryCANCmdType

    HAVE_CAN_DEVICE = True
except ModuleNotFoundError:
    HAVE_CAN_DEVICE = False

from autotrainer.core import (SystemStatusMessageKind, SystemCommandKind,
                              AudioSpectrumData, Offset3DTuple)

from .motor_steps import MotorSteps
from .device import Device
from .emulation_interface import EmulationInterface
from .device_api import DeviceApi
from autotrainer.core.analysis.head_fix_measurement import HeadFixMeasurement
from .can_interface import CanInterface
from .device_interface import (
    Acknowledge,
    AnalogOutput,
    AnalogOutputs,
    AudioData,
    DoorData,
    LoadCellReading,
    PressureReading,
    Motor,
    DigitalOutputs,
    Status,
    Tone,
    ColorLed,
    MagnetDigitalInputs,
    PelletDigitalInputs,
    ServoConfig,
    StepperConfig,
    SensorStatus,
    ServoStatus,
    StepperStatus,
    Version,
)


def _to_tuple(value: Union[str, Any]):
    if not isinstance(value, str):
        return value
    if "," in value:
        parts = value.split(",")
        return float(parts[0].strip()), float(parts[1].strip())
    else:
        return float(value)


def unpack_data_arg(data):
    if isinstance(data, SystemDataArgsKwargs):
        return data.args, data.kwargs
    return (data,), {}


def apply_system_command_with_data_args(func, data):
    args, kwargs = unpack_data_arg(data)
    return func(*args, **kwargs)


class CanDevice(Device):

    def __init__(self, api: DeviceApi = None, buffer_size: int = 50, force_emulation: bool = False):
        """
        Initialize the CANbus device interface.

        Args:
            api: The device API instance to use for communication
            buffer_size: Size of the measurement buffer
            force_emulation: Whether to force using emulation mode even if hardware is available
        """
        self._interface = \
            CanInterface() if HAVE_CAN_DEVICE and not force_emulation else EmulationInterface()
        super().__init__(self._interface, api)

        self._measurement_buffer_count = buffer_size
        self._measurements: List[HeadFixMeasurement] = []

        self._retract_distance = -15

        self._current_pressure = 0
        self._current_digital = 0
        self._current_temperature = 0
        self._current_humidity = 0
        self._current_audio = []

        self._pending_context = None
        self._pending_kind = None

        self._homing_motors = []

        self._load_pellet = default_load_pellet()
        self._send_pellet = default_send_pellet()
        self._cover_pellet = default_cover_pellet()
        self._release_pellet = default_release_pellet()
        self._open_tunnel_gate = default_open_gate()
        self._close_tunnel_gate = default_close_gate()
        self._compound_movement = None  # Current compound movement

        self._last_limit_switch = {
            Motor.PELLET_X_MOTOR: -1,
            Motor.PELLET_Y_MOTOR: -1,
            Motor.PELLET_Z_MOTOR: -1,
        }

        no_op_handler = lambda _: None

        # Initialize command handlers lookup table
        self._command_handlers = {
            SystemCommandKind.REQUEST_VERSION:
                lambda data: self._interface.request_version(),

            SystemCommandKind.READ_MOTOR_CONFIGURATION: self._interface.request_motor_config,

            SystemCommandKind.MOVE_MAGNET_SERVO: self._interface.move_magnet_servo,

            SystemCommandKind.MOVE_LOAD_SERVO: self._interface.move_load_servo,

            SystemCommandKind.MOVE_COVER_SERVO: self._interface.move_cover_servo,

            SystemCommandKind.MOVE_GATE_SERVO: self._interface.move_gate_servo,

            SystemCommandKind.SET_X: partial(apply_system_command_with_data_args,
                                             self._interface.set_motor_x),

            SystemCommandKind.SET_Y: partial(apply_system_command_with_data_args,
                                             self._interface.set_motor_y),

            SystemCommandKind.SET_Z: partial(apply_system_command_with_data_args,
                                             self._interface.set_motor_z),

            SystemCommandKind.MOVE_X: partial(apply_system_command_with_data_args,
                                              self._interface.move_motor_x),

            SystemCommandKind.MOVE_Y: partial(apply_system_command_with_data_args,
                                              self._interface.move_motor_y),

            SystemCommandKind.MOVE_Z: partial(apply_system_command_with_data_args,
                                              self._interface.move_motor_z),

            SystemCommandKind.SEND_RETRACT: self._send_retract,

            SystemCommandKind.SEND_TO_LIMITS:
                lambda data: self._home([cast(Motor, data)] if not isinstance(data, list) else data),

            SystemCommandKind.SEND_HOME:
                lambda data: self._home(
                    [Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR, Motor.PELLET_X_MOTOR]),

            SystemCommandKind.SEND_FIXED_XYZ:
                lambda _: self._interface.fixed_position(),

            SystemCommandKind.LOAD_PELLET:
                lambda _: self._start_sequence(self._load_pellet),

            SystemCommandKind.SEND_PELLET:
                lambda _: self._start_sequence(self._send_pellet),

            SystemCommandKind.RELEASE_PELLET:
                lambda _: self._start_sequence(self._release_pellet),

            SystemCommandKind.COVER_PELLET:
                lambda _: self._start_sequence(self._cover_pellet),

            SystemCommandKind.OPEN_TUNNEL_GATE:
                lambda _: self._start_sequence(self._open_tunnel_gate),

            SystemCommandKind.CLOSE_TUNNEL_GATE:
                lambda _: self._start_sequence(self._close_tunnel_gate),

            SystemCommandKind.DELAY: self._interface.delay,

            SystemCommandKind.WRITE_MOTOR_CONFIGURATION: self._handle_write_motor_configuration,

            SystemCommandKind.SET_LOAD_PELLET_PROCEDURE:
                lambda data: (
                    setattr(self, '_load_pellet', data)
                    if isinstance(data, MotorSteps) and not data.is_empty
                    else None
                ),

            SystemCommandKind.SET_SEND_PELLET_PROCEDURE:
                lambda data: (
                    setattr(self, '_send_pellet', data)
                    if isinstance(data, MotorSteps) and not data.is_empty
                    else None
                ),

            SystemCommandKind.SET_COVER_PELLET_PROCEDURE:
                lambda data: (
                    setattr(self, '_cover_pellet', data)
                    if isinstance(data, MotorSteps) and not data.is_empty
                    else None
                ),

            SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE:
                lambda data: (
                    setattr(self, '_release_pellet', data)
                    if isinstance(data, MotorSteps) and not data.is_empty
                    else None
                ),

            SystemCommandKind.UPDATE_SCALE_TARE: lambda _: self._interface.tare_load_cell(),

            SystemCommandKind.SET_DIGITAL_OUTPUT:
                lambda data: (
                    self._interface.set_digital_output(DigitalOutputs(data[0]), data[1] != 0)
                    if isinstance(data, tuple) else None
                ),

            SystemCommandKind.SET_ANALOG_OUTPUT:
                lambda data: (
                    self._interface.set_analog_output(AnalogOutputs(data[0]), data[1])
                    if isinstance(data, tuple) else None
                ),

            SystemCommandKind.SET_RGB_LED:
                lambda data: (
                    self._interface.set_color_led(data[0], data[1], data[2])
                    if isinstance(data, tuple) else None
                ),

            SystemCommandKind.PLAY_TONE:
                lambda data: (
                    self._interface.emit_tone(data[0], data[1]) if isinstance(data, tuple)
                    else self._interface.emit_tone(data, 500)  # 500 millisecond
                ),

            SystemCommandKind.SET_MOTOR_DRIFT: self._interface.set_motors_drift,
            SystemCommandKind.SET_AUTO_CORRECT_DRIFT: self._interface.set_auto_correct_motor_drift,

            # No-op handlers
            SystemCommandKind.STREAM_START: no_op_handler,
            SystemCommandKind.STREAM_STOP: no_op_handler,
        }

        #

        def set_current_pressure(m):
            self._current_pressure = m.pressure

        def set_current_temp_humidity(m):
            self._current_temperature = m.temperature_c
            self._current_humidity = m.humidity_percent

        def set_current_digital(m):
            self._current_digital = m.continuity_0

        # Initialize data handlers lookup table
        self._data_handlers = {
            Status: no_op_handler,  # No-op for Status messages
            Tone: no_op_handler,
            ColorLed: no_op_handler,
            AnalogOutput: no_op_handler,

            LoadCellReading: self._handle_load_cell_reading,
            PressureReading: set_current_pressure,
            SensorStatus: set_current_temp_humidity,

            MagnetDigitalInputs: set_current_digital,

            PelletDigitalInputs: lambda message: (
                self._api.send_message(SystemStatusMessageKind.STIMULUS_INPUTS,
                                       [message.stimulus_1,
                                        message.stimulus_2,
                                        message.stimulus_3,
                                        message.stimulus_4])
                if self._api is not None else None
            ),

            AudioData: lambda message: (
                self._api.send_message(SystemStatusMessageKind.AUDIO_SPECTRUM,
                                       AudioSpectrumData(when_val=message.when,
                                                         index_val=message.index,
                                                         magnitudes_val=message.magnitudes))
            ),

            StepperStatus: self._report_stepper_status,

            ServoStatus: lambda message: self._report_servo_status(message.motor, message.position),

            StepperConfig: lambda message: \
                self._api.send_message(SystemStatusMessageKind.MOTOR_CONFIGURATION, message),

            ServoConfig: lambda message: \
                self._api.send_message(SystemStatusMessageKind.MOTOR_CONFIGURATION, message),

            Version: lambda message: \
                self._api.send_message(SystemStatusMessageKind.FIRMWARE_VERSION, message.version),

            DoorData: lambda message: (
                self._api.send_message(SystemStatusMessageKind.FRONT_DOOR, message.door1 != 0),
                self._api.send_message(SystemStatusMessageKind.DRAWER_DOOR, message.door2 != 0),
                self._api.send_message(SystemStatusMessageKind.SPARE_DOOR, message.door3 != 0),
                self._api.send_message(SystemStatusMessageKind.EXT_BUTTON, message.ext_button != 0)
            ) if self._api is not None else None,

            Acknowledge: self._handle_ack,
        }

        if not HAVE_CAN_DEVICE:
            logger.warning(
                "Alogus hardware or hardware support not found.  Using emulation interface.")

        self._commands_queue = queue.Queue()
        self._commands_handler_thread = threading.Thread(
            target=self._command_handler, name="CanCommandHandler", daemon=True)
        self._commands_handler_thread.start()

    def get_motor_config(self, motor: Motor):
        return self._interface.get_motor_configuration(motor)

    def _set_move_x(self, position):
        steps = MotorSteps("set_move_x",
                           [{'x': position}, {'x': position, 'save_as_fixed': True}])
        return self._start_sequence(steps)

    def _set_move_y(self, position):
        steps = MotorSteps("set_move_y",
                           [{'y': position}, {'y': position, 'save_as_fixed': True}])
        return self._start_sequence(steps)

    def _set_move_z(self, position):
        steps = MotorSteps("set_move_z",
                           [{'z': position}, {'z': position, 'save_as_fixed': True}])
        return self._start_sequence(steps)

    def _send_retract(self, data):
        assert data is None
        del data
        self._interface.move_motor_y(self._retract_distance, relative=True)

    def _command_handler(self):
        cur_commands = []
        t_perf_last_command = None
        q = self._commands_queue
        has_read_from_queue = False
        pending_uuid = None
        while True:
            try:
                if has_read_from_queue:
                    q.task_done()
                r = q.get(timeout=0.005)
            except queue.Empty:
                r = None, None, None
                has_read_from_queue = False
            else:
                has_read_from_queue = True
            if r is None:
                q.task_done()
                logger.verbose("received exit sentinel, exiting main loop ..")
                break
            kind, data, ctx = r
            prev_commands_count = len(cur_commands)
            if kind == "uuid":
                if data == pending_uuid and pending_uuid is not None:
                    cur_commands.insert(0, r)
                else:
                    if pending_uuid is not None:
                        logger.verbose("Got CAN msg ack with uuid=%s but pending_uuid=%s", data, pending_uuid)
                    continue
            else:
                if kind is not None:
                    cur_commands.append(r)
            # if prev_commands_count != len(cur_commands):
            #     logger.debug("Commands changed: %s", cur_commands)
            if pending_uuid is not None and kind != "uuid":
                if time.perf_counter() < t_perf_last_command + 5:  # although could be set bit lower
                    continue
                logger.warning("timeout waiting ack previous command: %s ; context=%s",
                               self._pending_kind, self._pending_context)
                pending_uuid = None
            if len(cur_commands) == 0:
                continue
            kind, data, ctx = cur_commands.pop(0)
            before_uuid = self._interface.uuid()
            if kind == "uuid":
                logger.debug("executing ack perform next compound")
                pending_uuid = None
                self._perform_next_compound_step(data)
            else:
                handler = self._command_handlers.get(kind)
                if handler is None:
                    logger.warning("unhandled command queue message: %s", kind)
                    continue
                logger.debug("executing cmd %s with ctx %s", kind, ctx)
                handler(data)
            after_uuid = self._interface.uuid()
            t_perf_last_command = time.perf_counter()
            if after_uuid != before_uuid:
                # for now we have this rule:
                if after_uuid != before_uuid + 1 and (before_uuid != 255 or after_uuid != 1):
                    logger.warning("Unexpected uuid change count: before=%s after=%s", before_uuid, after_uuid)
                pending_uuid = after_uuid
                if ctx is not None:
                    if kind != "uuid":
                        self._pending_context = ctx
                        self._pending_kind = kind
            else:
                if kind != "uuid":
                    if ctx is not None:
                        logger.error("Handled %s with ctx=%s but CanInterface.uuid did not changed: %s",
                                     kind, ctx, after_uuid)
                    self._acknowledge_command(ctx)

    def _handle_ack(self, msg: Acknowledge):
        cur_can_uuid = CanInterface.uuid()
        logger.debug("Received ack: target=%s - uuid=%s ; cur_can_uuid=%s",
                     msg.target, msg.uuid, cur_can_uuid)
        self._commands_queue.put(("uuid", msg.uuid, None))

    @property
    def api(self):
        """
        Get the current device API instance.

        Returns:
            The current DeviceApi instance
        """
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        """
        Set the device API instance.

        Args:
            value: The DeviceApi instance to use
        """
        self._api = value

    def connect(self):
        pass

    def disconnect(self):
        self._commands_queue.put(None)
        self._commands_handler_thread.join(3)

    def _start_sequence(self, movements: MotorSteps):
        """
        Start a sequence of activities.

        Args:
            movements: The motor steps to execute
        """
        if movements is None or movements.is_empty:
            self._command_complete()
        else:
            self._compound_movement = movements.steps
            self._perform_next_compound_step()

    def _handle_write_motor_configuration(self, data):
        """
        Handle writing motor configuration.

        Args:
            data: A tuple containing motor and config
        """
        assert isinstance(data, Tuple)
        motor = data[0]
        config = data[1]
        assert isinstance(motor, Motor)
        assert isinstance(config, ServoConfig) or isinstance(config, StepperConfig)
        self._interface.set_motor_configuration(motor, config)

    def notify_message(
            self,
            kind: int,
            data: Union[str, float, int, SupportsInt],
            context: object = None,
    ) -> None:
        """
        This method is called when a command to a target is requested. This method
        translates the application command to the appropriate call to the CanInterface
        instance.
        
        Args:
            kind: The kind of system command
            data: The data associated with the command
            context: The context object for this command
        """
        if self._interface is None:
            return

        self._commands_queue.put((kind, data, context))
        return

        if self._pending_context is not None and context is not None:
            # logger.exception("pending_context not None: %s", self._pending_context)
            logger.warning("notify message %s while one in progress: %s ; pending context=%s new=%s",
                           kind, self._pending_kind, self._pending_context, context)

        if context is not None:
            self._pending_context = context
            self._pending_kind = kind

        # Get and execute handler if available
        handler = self._command_handlers.get(kind)
        if handler is not None:
            handler(data)
        else:
            logger.warning("unhandled command queue message: %s", kind)

    def notify_data(self, data: Any) -> None:
        """
        This method is called when data from the target is received. The data is
        forwarded to a DeviceAPI class.

        Args:
            data: The data received from the device
        """
        if self._api is None:
            return

        for message in data:
            # Get handler for the message type
            handler = self._data_handlers.get(type(message))
            if handler is not None:
                handler(message)
            else:
                logger.warning("Unhandled data type: %s", type(message))

    def _handle_load_cell_reading(self, message):
        """
        Handle a load cell reading message.

        Args:
            message: The LoadCellReading message
        """
        measurement = HeadFixMeasurement(
            when=message.timestamp_ns / 1e9,
            timestamp=message.index,
            weight=message.load,
            switch=self._current_digital,
            pressure=self._current_pressure,
            temperature=self._current_temperature,
            humidity=self._current_humidity,
        )

        self._measurements.append(measurement)

        if len(self._measurements) >= self._measurement_buffer_count:
            self._api.send_message(SystemStatusMessageKind.MEASUREMENTS,
                                   self._measurements.copy())
            self._measurements = list()

    def _command_complete(self, uuid: int = None) -> None:
        """
        On completion of a command, the class reports that to a DeviceAPI class.
        Note that 'completion' may only indicate that the message was sent to the
        target, not that the target is complete in executing the command.
        """
        self._acknowledge_command(self._pending_context)
        self._pending_kind = None
        self._pending_context = None  # last

    def _home(self, motors):
        """
        Transition a stepper motor to its home position, at the limit switch.

        Args:
            motors: List of motors to home
        """
        if len(motors) > 0:
            self._interface.stepper_home(motors[0])
            self._homing_motors = motors

    _motor_to_status_kind = {
        Motor.PELLET_X_MOTOR: SystemStatusMessageKind.PELLET_MOTOR_X,
        Motor.PELLET_Y_MOTOR: SystemStatusMessageKind.PELLET_MOTOR_Y,
        Motor.PELLET_Z_MOTOR: SystemStatusMessageKind.PELLET_MOTOR_Z,
        Motor.PELLET_LOAD_SERVO: SystemStatusMessageKind.PELLET_LOAD,
        Motor.PELLET_COVER_SERVO: SystemStatusMessageKind.PELLET_COVER,
        Motor.TUNNEL_MAGNET_SERVO: SystemStatusMessageKind.HEAD_MAGNET,
        Motor.TUNNEL_GATE_SERVO: SystemStatusMessageKind.TUNNEL_GATE_SERVO,
    }

    def _report_stepper_status(self, message: StepperStatus):
        """
        Report stepper status to the API.

        Args:
            message: StepperStatus
        """
        prev_limit_switch = self._last_limit_switch.get(message.motor, None)
        if message.is_at_limit != prev_limit_switch:
            logger.notice("%s: limit_switch: %s -> %s ; pos=%s",
                          message.motor, prev_limit_switch, message.is_at_limit, message.position)
            self._last_limit_switch[message.motor] = message.is_at_limit

        kind = CanDevice._motor_to_status_kind.get(message.motor, None)
        if self._api is not None and kind is not None:
            self.api.send_message(kind, message)

    def _report_servo_status(self, motor, position):
        """
        Report servo status to the API.

        Args:
            motor: The motor that has reported its status
            position: The current position of the motor
            _at_limit: Whether the motor is at its limit switch
        """

        kind = CanDevice._motor_to_status_kind.get(motor, None)

        if self._api is not None and kind is not None:
            self.api.send_message(kind, position)

    def _perform_next_compound_step(self, uuid: Optional[int] = None):
        """
        Issue the next step in a multi-step motor sequence.
        """
        if len(self._homing_motors) > 1:
            self._homing_motors.pop(0)  # first one is/was executed by _home() function
            self._home(self._homing_motors)
        elif self._compound_movement is not None and \
                len(self._compound_movement) > 0:
            step = self._compound_movement.pop(0)

            save_as_fixed = step.get("save_as_fixed", False)

            if "x" in step:
                location = _to_tuple(step["x"])
                self._interface.move_motor_x(location, save_as_fixed=save_as_fixed)
                logger.debug(f"X to {location}")

            elif "y" in step:
                location = _to_tuple(step["y"])
                self._interface.move_motor_y(location, save_as_fixed=save_as_fixed)
                logger.debug(f"Y to {location}")

            elif "z" in step:
                location = _to_tuple(step["z"])
                self._interface.move_motor_z(location, save_as_fixed=save_as_fixed)
                logger.debug(f"Z to {location}")

            elif "load_arm" in step:
                location = _to_tuple(step["load_arm"])
                self._interface.move_load_servo(location)
                logger.debug(f"Load Arm to {location}")

            elif "barrier_arm" in step:
                location = _to_tuple(step["barrier_arm"])
                self._interface.move_cover_servo(location)
                logger.debug(f"Barrier Arm to {location}")

            elif "magnet" in step:
                location = _to_tuple(step["magnet"])
                self._interface.move_magnet_servo(location)
                logger.debug(f"Magnet to {location}")

            elif "gate" in step:
                location = _to_tuple(step["gate"])
                self._interface.move_gate_servo(location)
                logger.debug(f"Gate to {location}")

            elif "delay" in step:
                duration = step["delay"]
                self._interface.delay(duration)
                logger.debug(f"delay for {duration}")

            elif "tone" in step:
                freq, duration = step["tone"].split(',')  # (hz), (sec)
                self._interface.emit_tone(int(freq), int(float(duration) * 1000))
                logger.debug(f"Emit Tone at {freq} for {duration}")

            elif "predefined" in step:
                predefined = step["predefined"]
                if predefined == "send":
                    self._interface.fixed_position()
                    logger.debug("Predefined Send")
                elif predefined == "cover":
                    self._interface.cover_pellet()
                    logger.debug("Predefined Cover (maximum)")
                elif predefined == "release":
                    self._interface.release_pellet()
                    logger.debug("Predefined Release (minimum)")
                elif predefined == "retrieve":
                    self._interface.retrieve_pellet()
                    logger.debug("Predefined Retrieve (maximum)")
                elif predefined == "scoop":
                    self._interface.scoop_pellet()
                    logger.debug("Predefined Scoop (minimum)")
                elif predefined == "home":
                    self._home([Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR, Motor.PELLET_X_MOTOR])
                else:
                    logger.warning("unhandled predefined: %s", predefined)
        else:
            self._command_complete()
            self._compound_movement = None
            self._homing_motors = []


def default_load_pellet() -> MotorSteps:
    """
    Create the default motor step sequence for loading a pellet.

    Returns:
        A MotorSteps object containing the load pellet sequence
    """
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
    """
    Create the default motor step sequence for sending a pellet.

    Returns:
        A MotorSteps object containing the send pellet sequence
    """
    return MotorSteps("send_pellet",
                      [
                          {'predefined': 'send'},
                      ]
                      )


def default_cover_pellet() -> MotorSteps:
    """
    Create the default motor step sequence for covering a pellet.

    Returns:
        A MotorSteps object containing the cover pellet sequence
    """
    return MotorSteps("cover_pellet",
                      [
                          {'predefined': 'cover'},
                      ]
                      )


def default_release_pellet() -> MotorSteps:
    """
    Create the default motor step sequence for releasing a pellet.

    Returns:
        A MotorSteps object containing the release pellet sequence
    """
    return MotorSteps("release_pellet",
                      [
                          {'predefined': 'release'},
                      ]
                      )


def default_open_gate() -> MotorSteps:
    """
    Create the default motor step sequence for releasing a pellet.

    Returns:
        A MotorSteps object containing the release pellet sequence
    """
    return MotorSteps("open_gate",
                      [
                          {'gate': '120'},
                      ]
                      )


def default_close_gate() -> MotorSteps:
    """
    Create the default motor step sequence for releasing a pellet.

    Returns:
        A MotorSteps object containing the release pellet sequence
    """
    return MotorSteps("close_gate",
                      [
                          {'gate': '0'},
                      ]
                      )
