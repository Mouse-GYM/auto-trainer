"""Assumes/requires real hardware is available and actively sending messages of some sort."""
import time
import pytest
import copy

try:
    from pyjerrycan import JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, JerryCAN
except ImportError:
    try:
        from autotrainer.device.pyjerryfile import JerryCAN, JerryCANMsg, JerryCANCfgMsg, \
            JerryCANCmdType
    except Exception:
        # Expected in some environments.
        pass

from autotrainer.device import WhiskerInterface, Heartbeat, ServoConfig, StepperConfig

DESTINATION_NODE = 0x01


@pytest.mark.whisker
def test_connect():
    """Verify CAN is available and accessible to supporting libraries (pyjerrycan)"""
    interface = WhiskerInterface()

    assert interface.open()
    return interface


@pytest.mark.whisker
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


@pytest.mark.whisker
def test_heartbeat(interface: WhiskerInterface, dst_id):
    """Verify ping"""
    assert interface.heartbeat()

    heartbeat = get_response(interface, Heartbeat, dst_id)

    assert heartbeat is not None
    assert heartbeat.src_id == dst_id


@pytest.mark.whisker
def test_read_servo_config(interface: WhiskerInterface, dst_id, motor_id: int):
    """Verify servo configuration can be read"""
    assert interface.request_servo_config(dst_id, motor_id)

    config = get_response(interface, ServoConfig, dst_id)

    assert config is not None
    assert config.src_id == dst_id
    assert config.motor_id == motor_id

    return config


@pytest.mark.whisker
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


@pytest.mark.whisker
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


@pytest.mark.whisker
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


def get_response(interface: WhiskerInterface, typeof, src_id: int, timeout: float = 0.2):
    now = time.time()

    while time.time() - now < timeout:
        messages = interface.read(100)
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

    for target in range(2):
        # magnet modules have bit at 0x4 set
        tgt = 4 if target == 0 else 1
        test_heartbeat(iface, tgt)
        # test_read(iface, tgt)
        servo_config = test_read_servo_config(iface, tgt, 0)
        test_write_servo_config(iface, tgt, servo_config)

        # only pellet modules have stepper motors
        if tgt < 4:
            stepper_config = test_read_stepper_config(iface, tgt, 0)
            test_write_stepper_config(iface, tgt, stepper_config)
    iface.close()

    # tone_write()
