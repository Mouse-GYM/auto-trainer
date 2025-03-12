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

from autotrainer.device import (WhiskerInterface, Heartbeat, ServoConfig, StepperConfig,
                                DigitalOutputs, MagnetDigitalInputs, PelletDigitalInputs, Tone,
                                AnalogOutputs, AnalogOutput)

DESTINATION_NODE = 0x01


@pytest.mark.canbus
def test_connect():
    """Verify CAN is available and accessible to supporting libraries (pyjerrycan)"""
    interface = WhiskerInterface()

    assert interface.open()
    return interface


@pytest.mark.canbus
def test_read(interface: WhiskerInterface, dst):
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
def test_heartbeat(interface: WhiskerInterface, dst_id):
    """Verify ping"""
    assert interface.heartbeat()

    heartbeat = get_response(interface, Heartbeat, dst_id, 2)

    assert heartbeat is not None
    assert heartbeat.src_id == dst_id


@pytest.mark.canbus
def test_read_servo_config(interface: WhiskerInterface, dst_id, motor_id: int):
    """Verify servo configuration can be read"""
    assert interface.request_servo_config(dst_id, motor_id)

    config = get_response(interface, ServoConfig, dst_id)

    assert config is not None
    assert config.src_id == dst_id
    assert config.motor_id == motor_id

    return config


@pytest.mark.canbus
def test_write_servo_config(interface: WhiskerInterface, dst_id: int, config: ServoConfig):
    """Verify servo configuration can be written"""
    orig_min = config.min_position
    orig_max = config.max_position

    config.min_position -= 10
    config.max_position += 10
    assert interface.write_servo_config(dst_id, config)

    new_config = test_read_servo_config(interface, dst_id, config.motor_id)
    assert new_config.min_position == config.min_position
    assert new_config.max_position == config.max_position

    config.min_position = orig_min
    config.max_position = orig_max

    assert interface.write_servo_config(dst_id, config)


@pytest.mark.canbus
def test_read_stepper_config(interface: WhiskerInterface, dst_id, motor_id: int):
    """Verify servo configuration can be read"""
    assert interface.request_stepper_config(dst_id, motor_id)

    config = get_response(interface, StepperConfig, dst_id)

    assert config is not None
    assert config.src_id == dst_id
    assert config.motor_id == motor_id

    return config


def write_stepper_config(interface: WhiskerInterface, dst_id: int, config: StepperConfig) -> bool:
    if not interface.write_stepper_config(dst_id, config):
        return False

    new_config = test_read_stepper_config(interface, dst_id, config.motor_id)

    return new_config.min_step_inverse == config.min_step_inverse and \
        new_config.steps_per_revolution == config.steps_per_revolution


@pytest.mark.canbus
def test_write_stepper_config(interface: WhiskerInterface, dst_id: int, config: StepperConfig):
    """Verify servo configuration can be written"""
    orig_min = config.min_step_inverse
    orig_steps = config.steps_per_revolution

    config.min_step_inverse *= 2
    config.steps_per_revolution *= 2
    assert write_stepper_config(interface, dst_id, config)

    config.min_step_inverse = orig_min
    config.steps_per_revolution = orig_steps
    assert write_stepper_config(interface, dst_id, config)


@pytest.mark.canbus
def test_write_gpio(interface: WhiskerInterface, dst_id: int, state: bool):
    assert interface.write_gpio(dst_id, DigitalOutputs.STIMULUS_1, state)

    for i in range(5):
        data = test_read_gpio(iface, tgt)
        if data is not None and data.stimulus_1 == state:
            assert True
            return

    assert False


@pytest.mark.canbus
def test_read_gpio(interface: WhiskerInterface, dst_id: int):
    if WhiskerInterface.is_pellet(dst_id):
        data = get_response(interface, PelletDigitalInputs, dst_id, 2.0)
    else:
        data = get_response(interface, MagnetDigitalInputs, dst_id, 2.0)

    assert data is not None

    return data


@pytest.mark.canbus
def test_tone(interface: WhiskerInterface, dst_id: int):
    if WhiskerInterface.is_pellet(dst_id):
        FREQUENCY_HZ = 1000
        DURATION_MS = 100
        assert interface.emit_tone(dst_id, FREQUENCY_HZ, DURATION_MS);

        tone = get_response(interface, Tone, dst_id)
        assert tone is not None
        assert tone.frequency_hz == FREQUENCY_HZ
        assert tone.time_remaining_ms <= DURATION_MS
    else:
        return


@pytest.mark.canbus
def test_analog_out(interface: WhiskerInterface, dst_id: int):
    if WhiskerInterface.is_pellet(dst_id):
        VALUE_MV = 1000
        assert interface.set_analog_output(dst_id, AnalogOutputs.STATUS_OUT, VALUE_MV);

        aout = get_response(interface, AnalogOutput, dst_id)
        assert aout is not None
        assert aout.status_out_mv == VALUE_MV
    else:
        return


def get_response(interface: WhiskerInterface, typeof, src_id: int, timeout: float = 1.1):
    now = time.time()

    while time.time() - now < timeout:
        messages = interface.read(10)
        # print ("len=", len(messages))
        if len(messages) > 0:
            for msg in messages:
                if isinstance(msg, typeof) and msg.src_id == src_id:
                    # print ("FOUND")
                    return msg
        time.sleep(0.001)

    return None


if __name__ == '__main__':
    iface = test_connect()
    for i in range(1):
        print(f"{i + 1}")
        for tgt in [1, 4]:
            # magnet modules have bit at 0x4 set
            for i in range(5):
                test_heartbeat(iface, tgt)
                # time.sleep(0.15)
            servo_config = test_read_servo_config(iface, tgt, 0)
            test_write_servo_config(iface, tgt, servo_config)

            # only pellet modules have stepper motors and digital outs
            if WhiskerInterface.is_pellet(tgt):
                stepper_config = test_read_stepper_config(iface, tgt, 0)
                test_write_stepper_config(iface, tgt, stepper_config)
                test_write_gpio(iface, tgt, True)
                test_write_gpio(iface, tgt, False)
                test_tone(iface, tgt)
                test_analog_out(iface, tgt)

    iface.close()
    # tone_write()
