"""
Device interface for the CANbus protocol to the Alogus device.

Extends the Device class that defines a fixed API to access the device. This
class relies on the CanInterface class to send and receive data.

"""
import collections
import copy
import logging
import math
import os
import queue
import threading
import time
from functools import partial
from typing import Tuple, Union, SupportsInt, List, Optional, Any, cast, Dict

from autotrainer.api import ApiEventKind
from autotrainer.api.api_event_kind import ApiDetectorKind

from autotrainer.core import Offset3DTuple, get_perf_now
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.message import SystemDataArgsKwargs
from autotrainer.core import ObservableObject, get_perf_now, EventManager


logger = get_verbose_logger(__name__)

_force_emulation = os.getenv("AUTOTRAINER_FORCE_CAN_EMULATION_IFACE", "") == "1"
if _force_emulation:
    HAVE_CAN_DEVICE = False
else:
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


_similar_data_refresh_delay = os.getenv("AUTOTRAINER_DEVICE_SIMILAR_DATA_REFRESH_DELAY") or 5
_similar_data_refresh_delay = float(_similar_data_refresh_delay)

# some sentinels object:

# this is used from CAN reader thread to put to CAN writer thread message queue :
_uuid_ack = object()

# this is used by CAN writer thread to manage its handling of internal queue of received commands to be executed.
_next_compound = object()

# for eventual retry when uuid ack timeout:
_retry_compound = object()
_retry_full = object()

_lambda_no_op = lambda: True


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

    default_command_write_failed_repeat_count: int = 3
    default_command_ack_timeout_duration: float = 3  # seconds
    default_command_ack_timeout_repeat_count: int = 3

    same_data_refresh_delay: float = _similar_data_refresh_delay
    """When > 0: if new data value is equal to previous value,
    and elapsed time since last one is smaller than this delay: skip data update.
    """

    _motor_to_status_kind = {
        Motor.PELLET_X_MOTOR: SystemStatusMessageKind.PELLET_MOTOR_X,
        Motor.PELLET_Y_MOTOR: SystemStatusMessageKind.PELLET_MOTOR_Y,
        Motor.PELLET_Z_MOTOR: SystemStatusMessageKind.PELLET_MOTOR_Z,
        Motor.PELLET_LOAD_SERVO: SystemStatusMessageKind.PELLET_LOAD,
        Motor.PELLET_COVER_SERVO: SystemStatusMessageKind.PELLET_COVER,
        Motor.TUNNEL_MAGNET_SERVO: SystemStatusMessageKind.HEAD_MAGNET,
        Motor.TUNNEL_GATE_SERVO: SystemStatusMessageKind.TUNNEL_GATE_SERVO,
        Motor.TUNNEL_FAN_SERVO: SystemStatusMessageKind.TUNNEL_FAN,
    }

    _motor_to_coordinate_char = {
        Motor.PELLET_X_MOTOR: "x",
        Motor.PELLET_Y_MOTOR: "y",
        Motor.PELLET_Z_MOTOR: "z",
    }
    _motor_to_coordinate_idx = {
        Motor.PELLET_X_MOTOR: 0,
        Motor.PELLET_Y_MOTOR: 1,
        Motor.PELLET_Z_MOTOR: 2,
    }

    def __init__(self, api: Optional[DeviceApi] = None, buffer_size: int = 50, force_emulation: bool = False):
        """
        Initialize the CANbus device interface.

        Args:
            api: The device API instance to use for communication
            buffer_size: Size of the measurement buffer
            force_emulation: Whether to force using emulation mode even if hardware is available
        """
        self._interface: Union[CanInterface, EmulationInterface] = \
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

        self._load_pellet = default_load_pellet()
        self._send_pellet = default_send_pellet()
        self._cover_pellet = default_cover_pellet()
        self._release_pellet = default_release_pellet()
        self._open_tunnel_gate = default_open_gate()
        self._close_tunnel_gate = default_close_gate()
        self._compound_movement: Optional[List[Dict[str, Any]]] = None  # Current compound movement

        self._last_limit_switch: Dict[Motor, Optional[bool]] = {
            Motor.PELLET_X_MOTOR: None,
            Motor.PELLET_Y_MOTOR: None,
            Motor.PELLET_Z_MOTOR: None,
        }
        self._last_pos = Offset3DTuple(math.nan, math.nan, math.nan)

        if not HAVE_CAN_DEVICE:
            logger.warning(
                "Alogus hardware or hardware support not found. Using emulation interface.")

        self._motor_configs: Dict[Motor, Union[StepperConfig, ServoConfig]] = {}

        self._init_handlers()

        self._prev_command: Optional[Tuple[object, Any, type(None)]] = None
        self._prev_command_is_relative = False

        self._commands_queue = queue.Queue()
        self._commands_handler_thread: Optional[threading.Thread] = None

        self._previous_stepper_status_perf_c = {}  # (None, -math.inf)
        self._previous_servo_status_perf_c = {}  # (None, -math.inf)

    def _init_handlers(self):

        no_op_handler = lambda _: True

        def inject_steps(steps):
            # replace current _internal_func with one doing nothing;
            self._compound_movement[0] = {"_internal_func": _lambda_no_op}
            # so that the inner steps are not re-injected on eventual write retry:
            self._compound_movement[1:1] = steps
            return True

        def handle_servo_move(motor: Motor, position):
            steps = self._make_servo_move_steps(motor, position)
            return self._start_sequence(MotorSteps(f"move_servo_{motor.name}", steps))

        def handle_servo_sequence(motor: Motor, sequence: MotorSteps):
            steps = self._make_servo_iface_func_steps(motor, lambda: inject_steps(sequence.steps))
            return self._start_sequence(MotorSteps(f"{motor.name}_{sequence.name}", steps))

        def set_load_pellet_proc(proc):
            if isinstance(proc, MotorSteps) and not proc.is_empty:
                self._load_pellet = proc
            return True

        def set_send_pellet_proc(proc):
            if isinstance(proc, MotorSteps) and not proc.is_empty:
                self._send_pellet = proc
            return True

        def set_cover_pellet_proc(proc):
            if isinstance(proc, MotorSteps) and not proc.is_empty:
                self._cover_pellet = proc
            return True

        def set_release_pellet_proc(proc):
            if isinstance(proc, MotorSteps) and not proc.is_empty:
                self._release_pellet = proc
            return True

        def apply_set_or_move(func, *args, **kwargs):
            has_relative = "relative" in kwargs
            is_relative = has_relative and kwargs["relative"]
            self._prev_command_is_relative = is_relative
            return func(*args, **kwargs)

        # Initialize command handlers lookup table
        self._command_handlers = {
            SystemCommandKind.REQUEST_VERSION:
                lambda data: self._interface.request_version(),

            SystemCommandKind.READ_MOTOR_CONFIGURATION: self._interface.request_motor_config,

            SystemCommandKind.MOVE_MAGNET_SERVO: partial(handle_servo_move, Motor.TUNNEL_MAGNET_SERVO),

            SystemCommandKind.MOVE_LOAD_SERVO: partial(handle_servo_move, Motor.PELLET_LOAD_SERVO),

            SystemCommandKind.MOVE_COVER_SERVO: partial(handle_servo_move, Motor.PELLET_COVER_SERVO),

            SystemCommandKind.MOVE_GATE_SERVO: partial(handle_servo_move, Motor.TUNNEL_GATE_SERVO),

            SystemCommandKind.SET_X: partial(apply_set_or_move, self._interface.set_motor_x),

            SystemCommandKind.SET_Y: partial(apply_set_or_move, self._interface.set_motor_y),

            SystemCommandKind.SET_Z: partial(apply_set_or_move, self._interface.set_motor_z),

            SystemCommandKind.MOVE_X: partial(apply_set_or_move, self._interface.move_motor_x),

            SystemCommandKind.MOVE_Y: partial(apply_set_or_move, self._interface.move_motor_y),

            SystemCommandKind.MOVE_Z: partial(apply_set_or_move, self._interface.move_motor_z),

            SystemCommandKind.SEND_RETRACT: self._send_retract,

            SystemCommandKind.SEND_TO_LIMITS:
                lambda data: self._start_sequence(MotorSteps(
                    "send_to_limits",
                    [{"home": d}
                     for d in (data if isinstance(data, (list, tuple)) else [data])
                     ]
                )),

            SystemCommandKind.SEND_HOME:
                lambda data: self._start_sequence(MotorSteps(
                    "send_home",
                    [{"home": m} for m in (Motor.PELLET_Y_MOTOR, Motor.PELLET_Z_MOTOR, Motor.PELLET_X_MOTOR)]
                )),

            SystemCommandKind.SEND_FIXED_XYZ: lambda _: self._interface.fixed_position(),

            # NB: the following sequences are using "predefined" move,
            # that are below automatically handled for possible servo attach/detach
            SystemCommandKind.LOAD_PELLET: lambda _: self._start_sequence(self._load_pellet),
            SystemCommandKind.SEND_PELLET: lambda _: self._start_sequence(self._send_pellet),

            SystemCommandKind.RELEASE_PELLET: lambda _: self._start_sequence(self._release_pellet),
            SystemCommandKind.COVER_PELLET: lambda _: self._start_sequence(self._cover_pellet),

            # on the other side we don't have "predefined" for open/close gate:
            SystemCommandKind.OPEN_TUNNEL_GATE: lambda _: handle_servo_sequence(Motor.TUNNEL_GATE_SERVO, self._open_tunnel_gate),
            SystemCommandKind.CLOSE_TUNNEL_GATE: lambda _: handle_servo_sequence(Motor.TUNNEL_GATE_SERVO, self._close_tunnel_gate),

            SystemCommandKind.TUNNEL_FAN_ON: \
                lambda _: self._interface.set_digital_output(DigitalOutputs(1), True),
            SystemCommandKind.TUNNEL_FAN_OFF:
                lambda _: self._interface.set_digital_output(DigitalOutputs(1), False),

            # digital only allow 2 "position"
            # SystemCommandKind.TUNNEL_FAN_SET: partial(handle_servo_move, Motor.TUNNEL_FAN_SERVO),

            #

            SystemCommandKind.DELAY: self._interface.delay,

            SystemCommandKind.WRITE_MOTOR_CONFIGURATION: self._handle_write_motor_configuration,

            SystemCommandKind.SET_LOAD_PELLET_PROCEDURE: set_load_pellet_proc,

            SystemCommandKind.SET_SEND_PELLET_PROCEDURE: set_send_pellet_proc,

            SystemCommandKind.SET_COVER_PELLET_PROCEDURE: set_cover_pellet_proc,

            SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE: set_release_pellet_proc,

            SystemCommandKind.UPDATE_SCALE_TARE: lambda _: self._interface.tare_load_cell(),

            SystemCommandKind.SET_DIGITAL_OUTPUT:
                lambda data: self._interface.set_digital_output(DigitalOutputs(data[0]), data[1]),

            SystemCommandKind.SET_ANALOG_OUTPUT:
                lambda data: self._interface.set_analog_output(AnalogOutputs(data[0]), data[1]),

            SystemCommandKind.SET_RGB_LED:
                lambda data: self._interface.set_color_led(data[0], data[1], data[2]),

            SystemCommandKind.PLAY_TONE:
                lambda data: (
                    self._interface.emit_tone(data[0], data[1]) if isinstance(data, tuple)
                    else self._interface.emit_tone(data, 500)  # 500 millisecond
                ),

            SystemCommandKind.SET_MOTOR_DRIFT: self._interface.set_motors_drift,
            SystemCommandKind.SET_AUTO_CORRECT_DRIFT: self._interface.set_auto_correct_motor_drift,

            SystemCommandKind.SERVO_ATTACH: self._interface.servo_attach,
            SystemCommandKind.SERVO_DETACH: self._interface.servo_detach,

            # No-op handlers
            SystemCommandKind.STREAM_START: no_op_handler,
            SystemCommandKind.STREAM_STOP: no_op_handler,
        }

        # Initialize data / response handlers lookup table

        def set_current_pressure(m):
            self._current_pressure = m.pressure

        def set_current_temp_humidity(m):
            self._current_temperature = m.temperature_c
            self._current_humidity = m.humidity_percent

        def set_current_digital(m):
            self._current_digital = m.continuity_0

        def handle_motor_config(m: Union[StepperConfig, ServoConfig]):
            # do we want to:
            #   self._motor_configs[m.motor] = m
            # as we do for written motor configs ? but probably better to not do it here.
            self._api.send_message(SystemStatusMessageKind.MOTOR_CONFIGURATION, m)

        previous_stimuli_data_perf_c = (None, -math.inf)
        def handle_stimuli_msg(m):
            nonlocal previous_stimuli_data_perf_c
            new_data = [m.stimulus_1, m.stimulus_2, m.stimulus_3, m.stimulus_4]
            prev_data, prev_perf_c = previous_stimuli_data_perf_c
            p_now = get_perf_now()
            if new_data != prev_data or p_now - prev_perf_c > self.same_data_refresh_delay:
                previous_stimuli_data_perf_c = (new_data, p_now)
                self._api.send_message(SystemStatusMessageKind.STIMULUS_INPUTS, new_data)

        previous_door_data_perf_c = (None, -math.inf)
        def handle_door_msg(m: DoorData):
            nonlocal previous_door_data_perf_c
            new_data = (m.door1, m.door2, m.door3, m.ext_button)
            p_now = get_perf_now()
            prev_data, prev_perf_c = previous_door_data_perf_c
            if new_data != prev_data or p_now - prev_perf_c > self.same_data_refresh_delay:
                previous_door_data_perf_c = (new_data, p_now)
                send_msg = self._api.send_message
                send_msg(SystemStatusMessageKind.FRONT_DOOR, m.door1 != 0),
                send_msg(SystemStatusMessageKind.DRAWER_DOOR, m.door2 != 0),
                send_msg(SystemStatusMessageKind.SPARE_DOOR, m.door3 != 0),
                send_msg(SystemStatusMessageKind.EXT_BUTTON, m.ext_button != 0)

        self._data_handlers = {
            Status: no_op_handler,  # No-op for Status messages
            Tone: no_op_handler,
            ColorLed: no_op_handler,
            AnalogOutput: no_op_handler,

            LoadCellReading: self._handle_load_cell_reading,
            PressureReading: set_current_pressure,
            SensorStatus: set_current_temp_humidity,

            MagnetDigitalInputs: set_current_digital,

            PelletDigitalInputs: handle_stimuli_msg,

            AudioData: lambda message: (
                self._api.send_message(SystemStatusMessageKind.AUDIO_SPECTRUM,
                                       AudioSpectrumData(when_val=message.when,
                                                         index_val=message.index,
                                                         magnitudes_val=message.magnitudes))
            ),

            StepperStatus: self._report_stepper_status,

            ServoStatus: lambda message: self._report_servo_status(message.motor, message.position),

            StepperConfig: handle_motor_config,
            ServoConfig: handle_motor_config,

            Version: lambda message: \
                self._api.send_message(SystemStatusMessageKind.FIRMWARE_VERSION, message.version),

            DoorData: handle_door_msg,

            Acknowledge: self._handle_ack,
        }

    def _put_to_cmd_queue(self, obj):
        cmd_thread = self._commands_handler_thread
        # cmd thread is started on connect()
        if cmd_thread is not None and not cmd_thread.is_alive():
            raise RuntimeError("CAN command handler thread not anymore alive: %s", cmd_thread)
        self._commands_queue.put(obj)

    def _send_retract(self, _):
        self._prev_command_is_relative = True
        return self._interface.move_motor_y(self._retract_distance, relative=True)

    def _command_handler(self):
        cur_commands = []
        t_perf_last_command_with_uuid = None
        q = self._commands_queue
        has_read_from_queue = False
        pending_uuid = None
        repeated_command_count = 0
        uuid_ack_timeout_engaged = False
        while True:
            if has_read_from_queue:
                q.task_done()
            try:
                raw = q.get(timeout=0.005)
            except queue.Empty:
                raw = None, None, None
                has_read_from_queue = False
            else:
                has_read_from_queue = True
            if raw is None:
                q.task_done()
                logger.verbose("received exit sentinel, exiting main loop ..")
                break
            kind, data, ctx = raw
            if kind is _uuid_ack:
                if data == pending_uuid and pending_uuid is not None:
                    cur_commands.insert(0, raw)
                    self._prev_command = None
                else:
                    if pending_uuid is not None:
                        logger.verbose("Got CAN msg ack with uuid=%s but pending_uuid=%s", data, pending_uuid)
                    else:
                        logger.debug("skipping unknown CAN uuid: %s", data)
                    continue
            else:
                if kind is not None:
                    cur_commands.append(raw)
            #
            has_compound_left = (
                self._compound_movement is not None
                and len(self._compound_movement) > 0
            )
            #
            if pending_uuid is not None and kind is not _uuid_ack:
                if time.perf_counter() - t_perf_last_command_with_uuid < self.default_command_ack_timeout_duration:
                    # continue poll input queue for uuid ack
                    continue
                if not uuid_ack_timeout_engaged:
                    uuid_ack_timeout_engaged = True
                    self.property_changed(self.UUID_ACK_TIMEOUT_ENGAGED, True, False)
                    EventManager.default().post_event_content(ApiEventKind.detectorChanged, context={
                        "detector_id": ApiDetectorKind.deviceAckTimeOut,
                        "is_active": True,
                        "is_enabled": True,
                    })
                logger.warning("timeout waiting ack previous command: %s ; context=%s ; pending_uuid=%s",
                               self._pending_kind, self._pending_context, pending_uuid)
                pending_uuid = None
                repeated_command_count += 1
                if repeated_command_count >= self.default_command_ack_timeout_repeat_count:
                    raise RuntimeError(f"Reached default_command_ack_timeout_repeat_count {repeated_command_count}")
                assert self._prev_command is not None
                if self._prev_command_is_relative:
                    raise RuntimeError(f"Command {self._prev_command} uuid ack timed out ; refusing retry given relative.")
                cur_commands.insert(0, self._prev_command)
                self._prev_command = None
                retrying = True
                time.sleep(0.1)  # do not retry eventually too fast to allow eventually reader thread
            else:
                retrying = False
            #
            if not retrying and has_compound_left:
                if pending_uuid is None:
                    cur_commands.insert(0, (_next_compound, None, None))  # will trigger perform next compound
                elif kind is not _uuid_ack:
                    continue
            if len(cur_commands) == 0:
                continue
            kind, data, ctx = cur_commands.pop(0)
            self._prev_command_is_relative = False  # always before trying new command, it's used on ack timeout
            before_uuid = self._interface.uuid()  # to know if some command has used, or not, a new CAN uuid
            success = False
            if kind is _retry_compound:
                self._compound_movement.insert(0, data)
                kind = _next_compound
            if kind is _next_compound:
                for _ in range(self.default_command_write_failed_repeat_count):
                    success = self._perform_next_compound_step()
                    if success:
                        break
                if not success:
                    raise RuntimeError("too many failure trying _perform_next_compound_step")
            elif kind is _uuid_ack:
                pending_uuid = None
                if uuid_ack_timeout_engaged:
                    uuid_ack_timeout_engaged = False
                    self.property_changed(self.UUID_ACK_TIMEOUT_ENGAGED, False, True)
                repeated_command_count = 0
                logger.debug("executing ack perform next compound")
                for _ in range(self.default_command_write_failed_repeat_count):
                    success = self._perform_next_compound_step()
                    if success:
                        break
                if not success:
                    raise RuntimeError("too many failure trying _perform_next_compound_step")
            else:
                if kind is _retry_full:
                    kind, data, ctx = data
                handler = self._command_handlers.get(kind)
                if handler is None:
                    logger.warning("unhandled command queue message: %s", kind)
                    continue
                success = False
                for _ in range(self.default_command_write_failed_repeat_count):
                    logger.debug("executing cmd %s with ctx %s", kind, ctx)
                    if isinstance(data, SystemDataArgsKwargs):
                        success = handler(*data.args, **data.kwargs)
                    else:
                        success = handler(data)
                    if success:
                        break
                    logger.error("Failed sending %s to bus", kind)
                if not success:
                    raise RuntimeError(f"Failed writing too many consecutive times to the device/bus. kind={kind.name} ctx={ctx}")
                #
                if ctx is not None:
                    if self._pending_context is not None:
                        logger.error("pending_context=%s and ctx=%s", self._pending_context, ctx)
                    else:
                        self._pending_context = ctx
                        self._pending_kind = kind
            # end possible handling cases
            after_uuid = self._interface.uuid()  # get CAN uuid after,
            if after_uuid != before_uuid:
                #
                # prev_commands_with_uuid_timeout_state.append(0)
                t_perf_last_command_with_uuid = time.perf_counter()
                # for now we have this rule:
                if after_uuid != before_uuid + 1 and (before_uuid != 255 or after_uuid != 1):
                    # but this can eventually happens if/when we retry several time the same (write-) command
                    logger.warning("Unexpected uuid change count: before=%s after=%s", before_uuid, after_uuid)
                #
                pending_uuid = after_uuid
                if ctx is not None:
                    if kind not in {_uuid_ack, _next_compound}:
                        self._pending_context = ctx
                        self._pending_kind = kind
                if self._prev_command is None:  # given compound step do set it itself
                    self._prev_command = (_retry_full, (kind, data, ctx), None)
            else:
                # no uuid generated
                has_compound_left = (
                    self._compound_movement is not None
                    and len(self._compound_movement) > 0
                )
                if kind not in {_uuid_ack, _next_compound}:
                    if self._pending_context is not None:
                        if not has_compound_left:
                            logger.warning("Handled %s with ctx=%s but CanInterface.uuid did not changed: %s",
                                         self._pending_kind, self._pending_kind, after_uuid)
                if not has_compound_left and self._pending_context is not None:
                    self._command_complete()

    def _handle_ack(self, msg: Acknowledge):
        cur_can_uuid = self._interface.uuid()
        logger.debug("Received ack: target=%s - uuid=%s ; cur_can_uuid=%s",
                     msg.target, msg.uuid, cur_can_uuid)
        self._put_to_cmd_queue((_uuid_ack, msg.uuid, None))

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
        # only start the command handler thread on connect,
        # which means we have already obtained the addr of desired devices.
        if self._commands_handler_thread is not None and self._commands_handler_thread.is_alive():
            logger.verbose("CAN command Handler thread already alive")
            return
        logger.info("Starting CanCommandHandler thread handler")
        thread = threading.Thread(
            target=self._command_handler, name="CanCommandHandler", daemon=True)
        thread.start()
        self._commands_handler_thread = thread  # only assign after start

    def disconnect(self):
        cmd_thread, cmd_queue = self._commands_handler_thread, self._commands_queue
        if cmd_thread is not None:
            if cmd_thread.is_alive():
                cmd_queue.put(None)
            cmd_thread.join(3)
            if cmd_thread.is_alive():
                logger.warning("%s still alive", cmd_thread)
            self._commands_handler_thread = None
            # cmd_queue.join()  # not totally necessary here

    def _start_sequence(self, movements: MotorSteps) -> bool:
        """
        Start a sequence of activities.

        Args:
            movements: The motor/device steps to execute
        """
        assert self._compound_movement is None
        if movements is None or movements.is_empty:
            logger.warning("start_sequence with empty or None sequence: %s", movements)
            self._command_complete()
            return True
        else:
            move_steps = movements.steps
            logger.info("Starting sequence %s (%s steps): %s", movements.name, len(move_steps), move_steps)
            self._compound_movement = move_steps
            return self._perform_next_compound_step()

    def _handle_write_motor_configuration(self, data: Tuple[Motor, Union[StepperConfig, ServoConfig]]):
        """
        Handle writing motor configuration.

        Args:
            data: A tuple containing motor and config
        """
        # assert isinstance(data, Tuple)
        motor = data[0]
        config = data[1]
        # assert isinstance(motor, Motor)
        # assert isinstance(config, (ServoConfig, StepperConfig))
        success = self._interface.set_motor_configuration(motor, config)
        if success:
            logger.debug("setting internal motor %s cfg to %s", motor, config)
            self._motor_configs[motor] = copy.deepcopy(config)
        return success

    def notify_message(
        self,
        kind: SystemCommandKind,
        data: Any,  # Union[str, float, int, SupportsInt],
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

        self._put_to_cmd_queue((kind, data, context))
        return

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

        measures = self._measurements
        measures.append(measurement)
        if len(measures) >= self._measurement_buffer_count:
            self._api.send_message(SystemStatusMessageKind.MEASUREMENTS, measures)
            self._measurements = []

    def _command_complete(self) -> None:
        """
        On completion of a command, the class reports that to a DeviceAPI class.
        Note that 'completion' may only indicate that the message was sent to the
        target, not that the target is complete in executing the command.
        NB: although with the CAN uuid ack that's what it actually means/signifies.
        """
        pending_ctx = self._pending_context
        if pending_ctx is not None:
            self._acknowledge_command(pending_ctx)
        self._prev_command = None
        self._compound_movement = None
        self._pending_kind = None
        self._pending_context = None  # last


    def _report_stepper_status(self, message: StepperStatus):
        """
        Report stepper status to the API.

        Args:
            message: StepperStatus
        """
        if message.motor in self._motor_to_coordinate_idx:
            prev_limit_switch = self._last_limit_switch[message.motor]
            last_pos = self._last_pos[self._motor_to_coordinate_idx[message.motor]]
            if message.is_at_limit != prev_limit_switch:
                logger.notice("%s: limit_switch: %s -> %s ; pos=%.02f (last=%.02f) send_pos=%.02f",
                              message.motor, prev_limit_switch, message.is_at_limit,
                              message.position, last_pos, message.send_position)
                self._last_limit_switch[message.motor] = message.is_at_limit
        coord_char = self._motor_to_coordinate_char.get(message.motor, None)
        if coord_char is not None:
            self._last_pos = self._last_pos.replace(**{coord_char: message.position})
        kind = CanDevice._motor_to_status_kind.get(message.motor, None)
        if self._api is not None and kind is not None:
            prev_data, prev_perf_c = self._previous_stepper_status_perf_c.get(kind, (None, -math.inf))
            perf_now = get_perf_now()
            data = (message.position, message.send_position, message.is_at_limit, message.position_error)
            if data != prev_data or perf_now - prev_perf_c > self.same_data_refresh_delay:
                self._previous_stepper_status_perf_c[kind] = (data, perf_now)
                self.api.send_message(kind, message)

    def _report_servo_status(self, motor, position):
        """
        Report servo status to the API.

        Args:
            motor: The motor that has reported its status
            position: The current position of the motor
        """
        kind = CanDevice._motor_to_status_kind.get(motor, None)
        if kind is None:
            return
        # if self._api is not None and kind is not None:
        prev_data, prev_perf_c = self._previous_servo_status_perf_c.get(kind, (None, -math.inf))
        perf_now = get_perf_now()
        if prev_data != position or perf_now - prev_perf_c > self.same_data_refresh_delay:
            self._previous_servo_status_perf_c[kind] = (position, perf_now)
            self.api.send_message(kind, position)

    #

    def _make_servo_steps(self, motor):
        cfg = self._motor_configs.get(motor, None)
        if cfg is None:
            logger.warning("%s: missing internal config", motor)
            want_detach = False
        else:
            want_detach = cfg.detach
        step = {}
        if want_detach:
            return step, [{'servo_attach': motor}, step, {'servo_detach': motor}]
        return step, [step]

    def _make_servo_move_steps(self, motor, position):
        step, steps = self._make_servo_steps(motor)
        step["_servo_move"] = (motor, position)
        return steps

    def _make_servo_iface_func_steps(self, motor, func):
        step, steps = self._make_servo_steps(motor)
        step['_internal_func'] = func
        return steps

    def _handle_servo_move_compound(self, compound_movements, motor, position):
        steps = self._make_servo_move_steps(motor, position)
        # replace current compound move by this new list of steps:
        # the [0] = : replace whatever previous step leaded to this _handle_servo_move_compound,
        # by one doing nothing now:
        compound_movements[0] = {"_internal_func": _lambda_no_op}  # noqa
        compound_movements[1:1] = steps
        return True

    def _handle_servo_iface_cmd_compound(self, compound_movements, motor, iface_func):
        steps = self._make_servo_iface_func_steps(motor, iface_func)
        # replace current compound move by this new list of steps:
        # the [0] = : replace whatever previous step leaded to this _handle_servo_iface_cmd_compound,
        # by one doing nothing now:
        compound_movements[0] = {"_internal_func": _lambda_no_op}  # noqa
        compound_movements[1:1] = steps
        return True

    def _perform_next_compound_step(self) -> bool:
        """
        Issue the next step in a multi-step motor sequence.
        """
        compound_movements = self._compound_movement
        if compound_movements is None or len(compound_movements) == 0:
            self._command_complete()
            return True

        step = compound_movements[0]
        logger.debug("executing next compound step: %s (remains=%s)",
                     step,
                     len(compound_movements) - 1,  # don't include current one
                     )

        assert isinstance(step, dict)
        save_as_fixed = step.get("save_as_fixed", False)

        if "x" in step:
            location = _to_tuple(step["x"])
            success = self._interface.move_motor_x(location, save_as_fixed=save_as_fixed)

        elif "y" in step:
            location = _to_tuple(step["y"])
            success = self._interface.move_motor_y(location, save_as_fixed=save_as_fixed)

        elif "z" in step:
            location = _to_tuple(step["z"])
            success = self._interface.move_motor_z(location, save_as_fixed=save_as_fixed)

        elif "_servo_move" in step:  # should be internal only
            motor, position = step["_servo_move"]  # noqa
            success = self._interface.move_servo_motor(motor, position)

        elif "load_arm" in step:
            location = _to_tuple(step["load_arm"])
            success = self._handle_servo_move_compound(compound_movements, Motor.PELLET_LOAD_SERVO, location)

        elif "barrier_arm" in step:
            location = _to_tuple(step["barrier_arm"])
            success = self._handle_servo_move_compound(compound_movements, Motor.PELLET_COVER_SERVO, location)

        elif "magnet" in step:
            location = _to_tuple(step["magnet"])
            success = self._handle_servo_move_compound(compound_movements, Motor.TUNNEL_MAGNET_SERVO, location)

        elif "gate" in step:
            location = _to_tuple(step["gate"])
            success = self._handle_servo_move_compound(compound_movements, Motor.TUNNEL_GATE_SERVO, location)

        # _servo_max_pos / _servo_max_pos are internal and should not be used from outside.
        elif "_servo_max_pos" in step:
            motor = step["_servo_max_pos"]  # noqa
            assert isinstance(motor, Motor)
            cfg = self._motor_configs.get(motor)
            if cfg is None:
                raise RuntimeError(f"Missing motor {motor} config. Config must be written by current connection/interface instance.")
            value = cfg.maximum_position
            success = self._interface.move_servo_motor(motor, value)
            if success:  # for log below/at end of func:
                step = {motor: value}

        elif "_servo_min_pos" in step:
            motor: Motor = step["_servo_min_pos"]  # noqa
            assert isinstance(motor, Motor)
            cfg = self._motor_configs.get(motor)
            if cfg is None:
                raise RuntimeError(f"Missing motor {motor} config. Config must be written by current connection/interface instance.")
            value = cfg.minimum_position
            success = self._interface.move_servo_motor(motor, value)
            if success:
                step = {motor: value}

        elif "delay" in step:
            duration = step["delay"]
            success = self._interface.delay(duration)

        elif "tone" in step:
            freq, duration = step["tone"].split(',')  # noqa  # (hz), (sec)
            success = self._interface.emit_tone(int(freq), int(float(duration) * 1000))

        elif "predefined" in step:

            predefined = step["predefined"]

            if predefined == "send":
                success = self._interface.fixed_position()

            elif predefined == "cover":
                success = self._handle_servo_iface_cmd_compound(
                    compound_movements, Motor.PELLET_COVER_SERVO, self._interface.cover_pellet)

            elif predefined == "release":
                success = self._handle_servo_iface_cmd_compound(
                    compound_movements, Motor.PELLET_COVER_SERVO, self._interface.release_pellet)

            elif predefined == "retrieve":
                success = self._handle_servo_iface_cmd_compound(
                    compound_movements, Motor.PELLET_LOAD_SERVO, self._interface.retrieve_pellet)

            elif predefined == "scoop":
                success = self._handle_servo_iface_cmd_compound(
                    compound_movements, Motor.PELLET_LOAD_SERVO, self._interface.scoop_pellet)

            elif predefined == "home":
                # replace by home steps (not predefined->home), 1 for each XYZ :
                step = {'home': Motor.PELLET_Y_MOTOR}  # for possible retry on ack timeout
                compound_movements[0] = step
                # inject at index 1 the steps:
                compound_movements[1:1] = [
                    {"home": m}
                    for m in [Motor.PELLET_Z_MOTOR, Motor.PELLET_X_MOTOR]
                ]
                success = self._interface.stepper_home(Motor.PELLET_Y_MOTOR)

            else:
                raise RuntimeError(f"Received unknown/unhandled compound step: {step}")
                # success = True
                # logger.error("Skipping unhandled predefined: %s", predefined)

        elif "servo_attach" in step:
            motor = step["servo_attach"]  # noqa
            assert isinstance(motor, Motor)
            success = self._interface.servo_attach(motor)

        elif "servo_detach" in step:
            motor = step["servo_detach"]  # noqa
            assert isinstance(motor, Motor)
            success = self._interface.servo_detach(motor)

        elif "home" in step:
            # NB: to not mix with predefined->home, which is 3 times this home but each with separate stepper.
            motor = step["home"]  # noqa
            assert isinstance(motor, Motor)
            success = self._interface.stepper_home(motor)

        elif "_internal_func" in step:
            func = step["_internal_func"]
            success = func()  # noqa

        else:
            raise RuntimeError(f"Received unknown/unhandled compound step: {step}")
            # logger.error("Skipping unknown compound step: %s", step)
            # success = True  # just skip it

        if success:
            compound_movements.pop(0)  # remove the one that was just requested successfully
            self._prev_command = (_retry_compound, step, None)  # in case need for retry for ack timeout
            logger.debug("executed %s write command", step)
        else:
            logger.error("%s write command failed", step)

        return success


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
    return MotorSteps("open_gate", [{'_servo_min_pos': Motor.TUNNEL_GATE_SERVO}])


def default_close_gate() -> MotorSteps:
    """
    Create the default motor step sequence for releasing a pellet.

    Returns:
        A MotorSteps object containing the release pellet sequence
    """
    return MotorSteps("close_gate", [{'_servo_max_pos': Motor.TUNNEL_GATE_SERVO}])
