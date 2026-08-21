import dataclasses
import logging
import math
import queue
import re
import threading
import time
import uuid
from functools import partial
from typing import Union
from unittest import mock

import pytest
from autotrainer.core import RawValueHolder
from autotrainer.core.observable_object import ObservableObject

from autotrainer.core.message import SystemStatusMessageKind, SystemCommandKind
from autotrainer.device import (
    CanDevice,
    DeviceApi,
    Target,
    LoadCellReading,
    PressureReading,
    SensorStatus,
    MagnetDigitalInputs,
    Motor,
    StepperStatus,
    ServoStatus,
    ServoConfig,
    StepperConfig,
    MotorSteps,
    DeviceConnection,
)
from autotrainer.device.can_device import (
    default_move_retract,
    default_load_pellet,
    default_send_pellet,
)
from autotrainer.device.device_interface import Acknowledge


@pytest.fixture(autouse=True)
def _use_mock_event_manager(mock_event_manager):
    pass


_expected = None

def data_callback(kind: int, response):
    assert kind == _expected
    del response  # uncheck atm


@pytest.fixture
def expected_tok() -> RawValueHolder:
    value = RawValueHolder(value=None)
    return value


def api_msg_cb(msg_kind, data, *, event, tokens_acked, expected_tok: RawValueHolder):
    # print(msg_kind, data)
    if msg_kind == SystemStatusMessageKind.ACKNOWLEDGE:
        tok, perf_c, error = data[:3]
        tokens_acked.append(tok)
        if tok is not None and tok == expected_tok.value:
            expected_tok.value = None
            if event is not None:
                event.set()


def assert_lines_in_logs(lines, caplog):
    logs = caplog.text.splitlines()
    while lines:
        xl = lines.pop(0)
        for idx, log in enumerate(logs):
            if xl in log:
                del logs[:idx + 1]
                break
        else:
            pytest.fail(f"don't find {xl} in log output: {caplog.text}")


@pytest.fixture
def tokens_acked():
    return []


@pytest.fixture
def expected_tok_event():
    return threading.Event()


@pytest.fixture
def device_conn(device):
    msg_q = queue.Queue()
    msg_cb = device.api.message_callback
    dc = DeviceConnection(device, message_queue=msg_q)
    dc.request_connect()
    device.api.message_callback = msg_cb
    try:
        yield dc
    finally:
        dc.request_disconnect()


@dataclasses.dataclass()
class DeviceAckTimeoutContext:
    engaged: bool = False
    engaged_count: int = 0


@pytest.fixture
def dev_ack_timeout_ctx():
    return DeviceAckTimeoutContext()


@pytest.fixture
def device(expected_tok_event, expected_tok, tokens_acked, dev_ack_timeout_ctx) -> CanDevice:  # noqa
    observable = ObservableObject(event_names=("message_callback",))
    device = CanDevice(api=DeviceApi(message_callback=data_callback), force_emulation=True)
    # unneeded, at least with emulation iface:
    # device._interface.magnet_address = 0x40
    # device._interface.pellet_address = 0x01
    # device.notify_message(_REQUEST_CONNECT)
    device.api.message_callback = observable.message_callback
    observable.message_callback += partial(
        api_msg_cb,
        tokens_acked=tokens_acked,
        expected_tok=expected_tok,
        event=expected_tok_event,
    )

    def dev_prop_changed(name, value, old):
        if name == device.UUID_ACK_TIMEOUT_ENGAGED:
            dev_ack_timeout_ctx.engaged = value
            if value:
                dev_ack_timeout_ctx.engaged_count += 1

    device.property_changed += dev_prop_changed

    device.connect()
    device.device_interface.open()
    try:
        yield device  # noqa
    finally:
        device.disconnect()


@pytest.mark.parametrize("kind, tag, data", [
    (SystemCommandKind.REQUEST_VERSION, 101, None),
    (SystemCommandKind.UPDATE_SCALE_TARE, 102, None),
    (SystemCommandKind.SET_X, 103, 10),
    (SystemCommandKind.SET_Y, 104, 15),
    (SystemCommandKind.SET_Z, 105, 20),
    (SystemCommandKind.MOVE_X, 106, 10),
    (SystemCommandKind.MOVE_Y, 106, 15),
    (SystemCommandKind.MOVE_Z, 108, 20),
    (SystemCommandKind.MOVE_MAGNET_SERVO, 109, 25),
    (SystemCommandKind.MOVE_GATE_SERVO, 110, 30),
    (SystemCommandKind.MOVE_LOAD_SERVO, 111, 35),
    (SystemCommandKind.MOVE_COVER_SERVO, 112, 40),
    (SystemCommandKind.SEND_HOME, 113, None),
    (SystemCommandKind.LOAD_PELLET, 114, None),
    (SystemCommandKind.SEND_PELLET, 115, None),
    (SystemCommandKind.RELEASE_PELLET, 116, None),
    (SystemCommandKind.COVER_PELLET, 117, None),
    (SystemCommandKind.PLAY_TONE, 118, None),
    (SystemCommandKind.DELAY, 119, 0.5),
    (SystemCommandKind.READ_MOTOR_CONFIGURATION, 120, Motor.PELLET_X_MOTOR),
    (SystemCommandKind.WRITE_MOTOR_CONFIGURATION, 121, (Motor.PELLET_X_MOTOR, StepperConfig())),
    (SystemCommandKind.SEND_FIXED_XYZ, 122, None),
    (SystemCommandKind.SEND_FIXED_XYZ, 123, None),
    (SystemCommandKind.SET_MOVE_RETRACT_PROCEDURE, 124, default_move_retract()),
])
def test_notify_command(device, kind, tag, data):
    device.notify_message(kind, data, tag)


@pytest.mark.parametrize("data, kind", [
    (LoadCellReading(target=Target.MAGNET_DEVICE, load=13), None),
    (PressureReading(Target.MAGNET_DEVICE, pressure=14), None),
    (SensorStatus(Target.PELLET_DEVICE, temperature_c=27.3, humidity_percent=64.2), None),
    (MagnetDigitalInputs(Target.MAGNET_DEVICE, continuity_0=False, continuity_1=True), None),
    (StepperStatus(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 10, 2.0, False),
     SystemStatusMessageKind.PELLET_MOTOR_X),
    (ServoStatus(Target.PELLET_DEVICE, Motor.PELLET_LOAD_SERVO, 40),
     SystemStatusMessageKind.PELLET_LOAD),
    (ServoConfig(Target.MAGNET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0, 0, 0, 0, 0),
     SystemStatusMessageKind.MOTOR_CONFIGURATION),
    (StepperConfig(Target.PELLET_DEVICE, Motor.PELLET_X_MOTOR, 0, 0, 0, 0, False),
     SystemStatusMessageKind.MOTOR_CONFIGURATION),
])
def test_notify_data(device, data, kind):
    global _expected

    if kind:
        _expected = kind

    device.notify_data([data])


@pytest.mark.parametrize("kind,data", (
    (SystemCommandKind.SET_MOVE_RETRACT_PROCEDURE, default_move_retract()),
    (SystemCommandKind.SET_LOAD_PELLET_PROCEDURE, default_load_pellet()),
    (SystemCommandKind.SET_SEND_PELLET_PROCEDURE, default_send_pellet()),
))
def test_set_procedures(
    expected_tok,
    expected_tok_event,
    tokens_acked,
    device,
    kind,
    data,
):
    ctx = uuid.uuid4()
    expected_tok.value = ctx
    device.notify_message(kind, data, context=ctx)
    expected_tok_event.wait(3)  # should be quite faster
    assert ctx in tokens_acked


def test_move_relative(
    expected_tok,
    expected_tok_event,
    tokens_acked,
    device,
    device_conn,
):
    # we rely on that on start:
    dev_positions = device.device_interface._positions  # noqa
    assert dev_positions[Motor.PELLET_X_MOTOR] == 0
    assert dev_positions[Motor.PELLET_Y_MOTOR] == 0
    ctx = uuid.uuid4()
    expected_tok.value = ctx
    device.notify_message(SystemCommandKind.SEND_RETRACT, None, context=ctx)
    expected_tok_event.wait(3)
    assert ctx in tokens_acked
    tokens_acked.clear()
    # emulation iface doesn't check motor limits, so the result position is 0 + retract_offset,
    # default one being -15, so we get -15 :
    assert math.isclose(dev_positions[Motor.PELLET_Y_MOTOR], -15, abs_tol=0.1)
    #
    expected_tok_event.clear()
    expected_tok.value = ctx
    device.notify_message(SystemCommandKind.SET_MOVE_RETRACT_PROCEDURE,
                          MotorSteps("custom", [{'y_rel': 20}, {'x_rel': -5}]),
                          context=ctx)
    expected_tok_event.wait(3)
    assert ctx in tokens_acked
    tokens_acked.clear()
    expected_tok_event.clear()
    expected_tok.value = ctx
    device.notify_message(SystemCommandKind.SEND_RETRACT, None, context=ctx)
    expected_tok_event.wait(3)
    assert ctx in tokens_acked
    # tokens_acked.clear()
    assert math.isclose(dev_positions[Motor.PELLET_X_MOTOR], -5, abs_tol=0.1)  # -5
    assert math.isclose(dev_positions[Motor.PELLET_Y_MOTOR], 5, abs_tol=0.1)  # -15 + 20 == 5


def test_can_connect_twice(device, caplog):
    with caplog.at_level(logging.DEBUG):
        device.connect()
    assert "CAN command Handler thread already alive" in caplog.text
    assert device.connected
    assert device.device_interface.is_open is True



def mock_device_method_uuid_ack_timeout(device, meth):
    orig_meth = getattr(device.device_interface, meth)

    def meth_with_uuid_ack_timeout(*args, **kwargs):
        # consume one uuid, but don't insert ack into return messages as with emulation iface
        device.device_interface.next_uuid()
        # restore orig method:
        setattr(device.device_interface, meth, orig_meth)
        # still return True to fake command written to CAN bus ok:
        return True

    m = mock.MagicMock(side_effect=meth_with_uuid_ack_timeout)
    setattr(device.device_interface, meth, m)
    device.default_command_ack_timeout_duration = 0.25  # make ~fast timeout


def test_rel_move_succeed_after_uuid_ack_timeout(
    expected_tok,
    expected_tok_event,
    tokens_acked,
    device,
    device_conn,
    dev_ack_timeout_ctx,
    monkeypatch,
    caplog,
):
    mock_device_method_uuid_ack_timeout(device, "move_motor_y")

    ctx = uuid.uuid4()
    expected_tok.value = ctx

    device.notify_message(SystemCommandKind.SEND_RETRACT, None, context=ctx)
    expected_tok_event.wait(3)

    assert ctx in tokens_acked
    assert not dev_ack_timeout_ctx.engaged
    assert dev_ack_timeout_ctx.engaged_count == 1
    assert device._commands_handler_thread.is_alive()

    msg = f"finished executing SystemCommandKind.SEND_RETRACT ; target_board=Target.PELLET_DEVICE ctx={ctx} board={ctx}"
    assert msg in caplog.text


def test_home_compound_with_first_fail(
    expected_tok,
    expected_tok_event,
    tokens_acked,
    device,
    device_conn,
    dev_ack_timeout_ctx,
    monkeypatch,
    caplog,
):
    mock_device_method_uuid_ack_timeout(device, "stepper_home")

    ctx = uuid.uuid4()
    expected_tok.value = ctx

    with caplog.at_level(logging.DEBUG):
        device.notify_message(SystemCommandKind.SEND_HOME, None, context=ctx)
        expected_tok_event.wait(3)

    assert ctx in tokens_acked
    assert not dev_ack_timeout_ctx.engaged
    assert dev_ack_timeout_ctx.engaged_count == 1
    assert device._commands_handler_thread.is_alive()
    #
    expected_ordered_lines = [
        "executing cmd SystemCommandKind.SEND_HOME with ctx",
        "Starting sequence send_home (3 steps):",
        "executing next compound step: {'home': <Motor.PELLET_Y_MOTOR: 3>} (remains after=2)",
        "timeout waiting ack previous command:",
        "retrying perform next compound with {'home': <Motor.PELLET_Y_MOTOR: 3>}",
        "executing next compound step: {'home': <Motor.PELLET_Y_MOTOR: 3>} (remains after=2)",
        "executed {'home': <Motor.PELLET_Y_MOTOR: 3>} write command",
        "executing next compound step: {'home': <Motor.PELLET_Z_MOTOR: 4>} (remains after=1)",
        "executing next compound step: {'home': <Motor.PELLET_X_MOTOR: 2>} (remains after=0)",
        f"finished executing SystemCommandKind.SEND_HOME ; target_board=Target.PELLET_DEVICE ctx={ctx} board={ctx}",
    ]
    assert_lines_in_logs(expected_ordered_lines, caplog)


def test_send_fixed_xyz_timedout(
    expected_tok,
    expected_tok_event,
    tokens_acked,
    device,
    device_conn,
    dev_ack_timeout_ctx,
    monkeypatch,
    caplog,
):
    mock_device_method_uuid_ack_timeout(device, "fixed_position")

    ctx = uuid.uuid4()
    expected_tok.value = ctx

    with caplog.at_level(logging.DEBUG):
        device.notify_message(SystemCommandKind.SEND_FIXED_XYZ, None, context=ctx)
        expected_tok_event.wait(3)

    assert ctx in tokens_acked
    assert not dev_ack_timeout_ctx.engaged
    assert dev_ack_timeout_ctx.engaged_count == 1
    assert device._commands_handler_thread.is_alive()
    #
    expected_ordered_lines = [
        "executing cmd SystemCommandKind.SEND_FIXED_XYZ",
        "timeout waiting ack previous command: SystemCommandKind.SEND_FIXED_XYZ",
        "executing command kind: retry_full",
        "executing cmd SystemCommandKind.SEND_FIXED_XYZ",
        "finished executing SystemCommandKind.SEND_FIXED_XYZ",
    ]
    assert_lines_in_logs(expected_ordered_lines, caplog)


@pytest.mark.parametrize("fail_all_retries", [False, True])
@pytest.mark.parametrize("max_command_repeat_count", [1, 3])
def test_command_with_uuid_error(
    expected_tok,
    expected_tok_event,
    tokens_acked,
    device,
    device_conn,
    dev_ack_timeout_ctx,
    monkeypatch,
    caplog,
    fail_all_retries,
    max_command_repeat_count,
):
    device.default_max_failed_command_count = max_command_repeat_count
    api = device.api
    iface = device.device_interface
    uuid_ack_err_code = 133

    # patch move_servo_motor, which is used for the following command we send (OPEN_TUNNEL_GATE)
    orig_move_servo_motor = iface.move_servo_motor
    def patched(
        motor: Motor, position
    ):
        if isinstance(position, tuple):
            position = position[0]
        iface._positions[motor] = position  # noqa
        iface._messages.append(Acknowledge(uuid=iface.next_uuid(), error=uuid_ack_err_code))  # noqa
        if not fail_all_retries:
            iface.move_servo_motor = orig_move_servo_motor
        return True
    monkeypatch.setattr(iface, "move_servo_motor", mock.MagicMock(spec=iface.move_servo_motor, side_effect=patched))

    orig_api_cb = api.message_callback
    ack_received = None
    def recv_cb(kind, data):
        nonlocal ack_received
        if kind == SystemStatusMessageKind.ACKNOWLEDGE:
            # print(kind, data)
            if data[0] == ctx:
                ack_received = data
        orig_api_cb(kind, data)

    api.message_callback = recv_cb

    ctx = uuid.uuid4()
    expected_tok.value = ctx

    with caplog.at_level(logging.DEBUG):
        device.notify_message(SystemCommandKind.OPEN_TUNNEL_GATE, None, context=ctx)
        assert expected_tok_event.wait(3)
    assert ack_received is not None, "should have received the ack, even if possibly with error"
    ack_tok, ack_perf, ack_err = ack_received
    expected_err = f"Reached default_repeated_failed_command_count {max_command_repeat_count} on board <Target.PELLET_DEVICE: 0>"
    if fail_all_retries or max_command_repeat_count <= 1:
        assert ack_err == expected_err
    else:
        assert ack_err is None
    assert f"ctx={ctx} kind={SystemCommandKind.OPEN_TUNNEL_GATE!s} error={uuid_ack_err_code} " in caplog.text

    # also ensure that board remains in error after:
    if fail_all_retries or max_command_repeat_count <= 1:
        ctx = uuid.uuid4()
        expected_tok.value = ctx
        iface.move_servo_motor = orig_move_servo_motor
        expected_tok_event.clear()
        ack_received = None
        with caplog.at_level(logging.DEBUG):
            device.notify_message(SystemCommandKind.OPEN_TUNNEL_GATE, None, context=ctx)
            assert expected_tok_event.wait(3)
        assert ack_received is not None, (
            "should have received the ack, with error"
        )
        ack_tok, ack_perf, ack_err = ack_received
        assert ack_err == expected_err  # still
