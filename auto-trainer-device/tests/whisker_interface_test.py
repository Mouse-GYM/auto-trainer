"""Assumes/requires real hardware is available and actively sending messages of some sort."""
import time
import pytest

try:
    from pyjerrycan import JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, JerryCAN
except ImportError:
    try:
        from autotrainer.device.pyjerryfile import JerryCAN, JerryCANMsg, JerryCANCfgMsg, \
            JerryCANCmdType
    except Exception:
        # Expected in some environments.
        pass

from autotrainer.device import (WhiskerInterface, Target, Heartbeat, ServoConfig, StepperConfig,
                                DigitalOutputs, MagnetDigitalInputs, PelletDigitalInputs, Tone,
                                AnalogOutputs, AnalogOutput, LoadCellReading, PressureReading)

MAGNET_ADDRESS = 4
PELLET_ADDRESS = 1


@pytest.mark.canbus
def test_connect():
    """Verify CAN is available and accessible to supporting libraries (pyjerrycan)"""
    interface = WhiskerInterface()

    assert interface.open()

    interface.set_magnet_address(addr=int(MAGNET_ADDRESS))
    interface.set_pellet_address(addr=int(PELLET_ADDRESS))

    return interface


@pytest.mark.canbus
def test_read(interface: WhiskerInterface):
    """Verify interface read() returns jerrycan messages"""

    # Ensure messages start arriving.
    time.sleep(0.1)

    # Verify returns one message by default.
    messages = interface.read()
    assert isinstance(messages, list) and len(messages) == 1
    assert isinstance(messages[0], JerryCANMsg)

    # Verify can return multiple messages.
    cnt = 3
    messages = interface.read(cnt)
    assert isinstance(messages, list) and len(messages) == cnt


@pytest.mark.canbus
def test_heartbeat(interface: WhiskerInterface, target: Target):
    """Verify ping"""
    assert interface.heartbeat()

    heartbeat = get_response(interface, Heartbeat, target, 2)

    assert heartbeat is not None


@pytest.mark.canbus
def test_read_servo_config(interface: WhiskerInterface, target: Target, motor_id: int):
    """Verify servo configuration can be read"""
    assert interface.request_servo_config(target, motor_id)

    config = get_response(interface, ServoConfig, target)

    assert config is not None
    assert config.motor_id == motor_id

    return config


@pytest.mark.canbus
def test_write_servo_config(interface: WhiskerInterface, target: Target, config: ServoConfig):
    """Verify servo configuration can be written"""
    orig_min = config.min_position
    orig_max = config.max_position

    config.min_position -= 10
    config.max_position += 10
    assert interface.write_servo_config(target, config)

    new_config = test_read_servo_config(interface, target, config.motor_id)
    assert new_config.min_position == config.min_position
    assert new_config.max_position == config.max_position

    config.min_position = orig_min
    config.max_position = orig_max

    assert interface.write_servo_config(target, config)


@pytest.mark.canbus
def test_read_stepper_config(interface: WhiskerInterface, motor_id: int):
    """Verify servo configuration can be read"""
    assert interface.request_stepper_config(motor_id)

    config = get_response(interface, StepperConfig, Target.PELLET_DEVICE)

    assert config is not None
    assert config.motor_id == motor_id

    return config


def write_stepper_config(interface: WhiskerInterface, config: StepperConfig) -> bool:
    if not interface.write_stepper_config(config):
        return False

    new_config = test_read_stepper_config(interface, config.motor_id)

    return new_config.min_step_inverse == config.min_step_inverse and \
        new_config.steps_per_revolution == config.steps_per_revolution


@pytest.mark.canbus
def test_write_stepper_config(interface: WhiskerInterface, config: StepperConfig):
    """Verify servo configuration can be written"""
    orig_min = config.min_step_inverse
    orig_steps = config.steps_per_revolution

    config.min_step_inverse *= 2
    config.steps_per_revolution *= 2
    assert write_stepper_config(interface, config)

    config.min_step_inverse = orig_min
    config.steps_per_revolution = orig_steps
    assert write_stepper_config(interface, config)


@pytest.mark.canbus
def test_write_gpio(interface: WhiskerInterface, state: bool):
    assert interface.write_gpio(DigitalOutputs.STIMULUS_1, state)

    for tries in range(5):
        data = test_read_gpio(iface, tgt)
        if data is not None and data.stimulus_1 == state:
            assert True
            return

    assert False


@pytest.mark.canbus
def test_read_gpio(interface: WhiskerInterface, target: Target):
    data = get_response(interface, PelletDigitalInputs, target, 2.0)
    assert data is not None
    return data


@pytest.mark.canbus
def test_tone(interface: WhiskerInterface):
    frequency_hz = 1000
    duration_ms = 100
    assert interface.emit_tone(frequency_hz, duration_ms);

    tone = get_response(interface, Tone, Target.PELLET_DEVICE)
    assert tone is not None
    assert tone.frequency_hz == frequency_hz
    assert tone.time_remaining_ms <= duration_ms


@pytest.mark.canbus
def test_analog_out(interface: WhiskerInterface):
    value_mv = 1000
    assert interface.set_analog_output(AnalogOutputs.STATUS_OUT, value_mv);

    aout = get_response(interface, AnalogOutput, Target.PELLET_DEVICE)
    assert aout is not None
    assert aout.status_out_mv == value_mv


@pytest.mark.canbus
def test_tare_load_cell(interface: WhiskerInterface):
    assert interface.tare_load_cell();

    for tries in range(3):
        loadcell = get_response(interface, LoadCellReading, Target.MAGNET_DEVICE)
        assert loadcell is not None
        # TODO - check when there is real hardware
        # print(loadcell.load_mv)
        # if loadcell.load_mv == 0:
        #     return
        return

    assert False


@pytest.mark.canbus
def test_tare_pressure_sensor(interface: WhiskerInterface):
    assert interface.tare_pressure_sensor();

    for tries in range(3):
        pressure = get_response(interface, PressureReading, Target.MAGNET_DEVICE)
        assert pressure is not None
        # TODO - check when there is real hardware
        # print(pressure.pressure_mv)
        # if pressure.pressure_mv == 0:
        #     return
        return

    assert False


def get_response(interface: WhiskerInterface, typeof, target: Target, timeout: float = 1.1):
    now = time.time()

    while time.time() - now < timeout:
        messages = interface.read(10)
        # print ("len=", len(messages))
        if len(messages) > 0:
            for msg in messages:
                if isinstance(msg, typeof) and msg.target == target:
                    # print ("FOUND")
                    return msg
        time.sleep(0.001)

    return None


if __name__ == '__main__':
    iface = test_connect()

    for i in range(1):
        print(f"{i + 1}")
        for tgt in [Target.PELLET_DEVICE, Target.MAGNET_DEVICE]:
            # magnet modules have bit at 0x4 set
            for j in range(5):
                test_heartbeat(iface, tgt)
                # time.sleep(0.15)
            servo_config = test_read_servo_config(iface, tgt, 0)
            test_write_servo_config(iface, tgt, servo_config)

    # Pellet or Magnet-only capabilities
    for i in range(1):
        print(f"{i + 1}")
        stepper_config = test_read_stepper_config(iface, 0)
        test_write_stepper_config(iface, stepper_config)
        test_write_gpio(iface, True)
        test_write_gpio(iface, False)
        test_tone(iface)
        test_analog_out(iface)
        test_tare_load_cell(iface)
        test_tare_pressure_sensor(iface)

    iface.close()
    # tone_write()
