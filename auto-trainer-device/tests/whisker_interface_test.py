"""Assumes/requires real hardware is available and actively sending messages of some sort."""
import time
import pytest

try:
    from pyjerrycan import JerryCANMsg, JerryCANCmdType, JerryCANCfgMsg, JerryCAN
except ImportError:
    try:
        from autotrainer.device.pyjerryfile import JerryCAN, JerryCANMsg, JerryCANCfgMsg, JerryCANCmdType
    except Exception:
        # Expected in some environments.
        pass

from autotrainer.device import WhiskerInterface

DESTINATION_NODE = 0x01


@pytest.mark.whisker
def test_connect():
    """Verify CAN is available and accessible to supporting libraries (pyjerrycan)"""
    interface = WhiskerInterface(DESTINATION_NODE)

    assert interface.open() == 1

    interface.close()


@pytest.mark.whisker
def test_read():
    """Verify interface read() returns jerrycan messages"""
    interface = WhiskerInterface(DESTINATION_NODE)

    # Verify before open, should return empty list.
    messages = interface.read()

    assert isinstance(messages, list) and len(messages) == 0

    assert interface.open() == 1

    # Ensure messages start arriving.
    time.sleep(0.5)

    # Verify returns one message by default.
    messages = interface.read()

    assert isinstance(messages, list) and len(messages) == 1

    assert isinstance(messages[0], JerryCANMsg)

    # Verify can return multiple messages.
    messages = interface.read(3)

    assert isinstance(messages, list) and len(messages) == 3

    # Verify if asking for more messages than can be buffered or sent in a short time, returns on None receive with
    # fewer messages.

    # TEST_FAILURE: This is not a robust way to choose what _should_ run out of available messages
    messages = interface.read(1000)

    assert isinstance(messages, list) and len(messages) < 1000

    interface.close()


@pytest.mark.whisker
def test_servo_config():
    """Verify servo configuration can be configured and read"""
    interface = WhiskerInterface(0x00)

    assert interface.open() == 1

    assert interface.request_servo_read(0)

    now = time.time()

    config = get_config_response(interface)

    assert config is not None

    assert config.type == JerryCANCfgMsg.Type.SERVO

    config_data = config.servo

    interface.close()


def get_response(interface: WhiskerInterface, msg_type: JerryCANCmdType, timeout: float = 2.5):
    now = time.time()

    while time.time() - now < timeout:
        messages = interface.read()
        if len(messages) > 0:
            msg = messages[0]
            if msg and msg.type == msg_type and msg.dst_id == interface.destination:
                return msg
        time.sleep(0.001)

    return None


def get_config_response(interface: WhiskerInterface, timeout: float = 2.5):
    message = get_response(interface, JerryCANCmdType.CFG_RESPONSE, timeout)

    if message is not None:
        return message.cfg_response

    return None


if __name__ == '__main__':
    test_connect()

    test_read()

    test_servo_config()

    tone_write()
