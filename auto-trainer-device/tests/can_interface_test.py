"""Assumes/requires real hardware is available and actively sending messages of some sort."""
import time
import pytest

from autotrainer.device import (CanInterface, Target, Motor, Heartbeat, ServoConfig, StepperConfig,
                                DigitalOutputs, MagnetDigitalInputs, PelletDigitalInputs, Tone,
                                AnalogOutputs, AnalogOutput, LoadCellReading, PressureReading,
                                ColorLed, AudioData, DoorData, ServoStatus, StepperStatus,
                                SensorStatus)

MAGNET_ADDRESS = 4
PELLET_ADDRESS = 1


@pytest.mark.canbus
def test_connect():
    global MAGNET_ADDRESS, PELLET_ADDRESS

    interface = CanInterface()

    assert interface.open()

    interface.set_magnet_address(MAGNET_ADDRESS)
    interface.set_pellet_address(PELLET_ADDRESS)

    return interface


@pytest.mark.canbus
def test_read(interface: CanInterface):
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
def test_heartbeat(interface: CanInterface, target: Target):
    """Verify ping"""
    assert interface.send_heartbeat()

    heartbeat = get_response(interface, Heartbeat, target, 2)

    assert heartbeat is not None


@pytest.mark.canbus
def test_read_servo_config(interface: CanInterface, target: Target, motor: Motor):
    """Verify servo configuration can be read"""
    assert interface.request_servo_config(target, motor)

    config = get_response(interface, ServoConfig, target)

    assert config is not None
    assert config.motor is motor

    return config


@pytest.mark.canbus
def test_write_servo_config(interface: CanInterface, target: Target, config: ServoConfig):
    """Verify servo configuration can be written"""
    orig_min = config.min_position
    orig_max = config.max_position

    config.min_position -= 10
    config.max_position += 10
    assert interface.write_servo_config(target, config)

    new_config = test_read_servo_config(interface, target, config.motor)
    assert new_config.min_position == config.min_position
    assert new_config.max_position == config.max_position

    config.min_position = orig_min
    config.max_position = orig_max

    assert interface.write_servo_config(target, config)


@pytest.mark.canbus
def test_read_stepper_config(interface: CanInterface, motor: Motor):
    """Verify servo configuration can be read"""
    assert interface.request_stepper_config(motor)

    config = get_response(interface, StepperConfig, Target.PELLET_DEVICE)

    assert config is not None
    assert config.motor is motor

    return config


def write_stepper_config(interface: CanInterface, config: StepperConfig) -> bool:
    if not interface.write_stepper_config(config):
        return False

    new_config = test_read_stepper_config(interface, config.motor)

    return new_config.min_step_inverse == config.min_step_inverse and \
        new_config.steps_per_revolution == config.steps_per_revolution


@pytest.mark.canbus
def test_write_stepper_config(interface: CanInterface, config: StepperConfig):
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
def test_write_gpio(interface: CanInterface, state: bool):
    assert interface.set_digital_output(DigitalOutputs.STIMULUS_1, state)

    for tries in range(5):
        data = test_read_gpio(iface, Target.PELLET_DEVICE)
        if data is not None and data.stimulus_1 == state:
            assert True
            return

    assert False


@pytest.mark.canbus
def test_read_gpio(interface: CanInterface, target: Target):
    data = get_response(interface, PelletDigitalInputs, target, 2.0)
    assert data is not None
    return data


@pytest.mark.canbus
def test_tone(interface: CanInterface):
    frequency_hz = 1500
    duration_ms = 400
    assert interface.emit_tone(frequency_hz, duration_ms);

    # give it a chance to update
    for retry in range(3):
        tone = get_response(interface, Tone, Target.PELLET_DEVICE)
    assert tone is not None
    assert tone.frequency_hz == frequency_hz
    assert tone.time_remaining_ms <= duration_ms


@pytest.mark.canbus
def test_analog_out(interface: CanInterface):
    value_mv = 1000
    assert interface.set_analog_output(AnalogOutputs.STATUS_OUT, value_mv);

    aout = get_response(interface, AnalogOutput, Target.PELLET_DEVICE)
    assert aout is not None
    assert aout.status_out_mv == value_mv


@pytest.mark.canbus
def test_tare_load_cell(interface: CanInterface):
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
def test_tare_pressure_sensor(interface: CanInterface):
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


@pytest.mark.canbus
def test_color_led(interface: CanInterface):
    red = 25
    green = 50
    blue = 75

    assert interface.set_color_led(red, green, blue)
    # Allow the data to catch up with the command
    for tries in range(3):
        led = get_response(interface, ColorLed, Target.PELLET_DEVICE)
    assert led is not None
    assert led.red == red
    assert led.green == green
    assert led.blue == blue


def test_streaming_data(interface: CanInterface):
    audio = get_response(interface, AudioData, Target.PELLET_DEVICE, 3.0)
    assert audio is None or len(audio.magnitudes) == 32

    door = get_response(interface, DoorData, Target.PELLET_DEVICE)
    assert door is not None
    assert len(door.open_state) == 3

    status = get_response(interface, ServoStatus, Target.PELLET_DEVICE)
    assert status is not None

    status = get_response(interface, ServoStatus, Target.MAGNET_DEVICE)
    assert status is not None

    status = get_response(interface, StepperStatus, Target.PELLET_DEVICE)
    assert status is not None

    # TODO Needs Temp/Hum sensor
    # status = get_response(interface, SensorStatus, Target.MAGNET_DEVICE)
    # assert status is not None


def get_response(interface: CanInterface, typeof, target: Target, timeout: float = 2.0):
    now = time.time()

    while time.time() - now < timeout:
        messages = interface.read(1)
        if len(messages) > 0:
            for msg in messages:
                if isinstance(msg, typeof) and msg.target is target:
                    return msg
        time.sleep(0.001)

    return None


if __name__ == '__main__':
    iface = test_connect()

    test_heartbeat(iface, Target.PELLET_DEVICE)
    test_heartbeat(iface, Target.MAGNET_DEVICE)

    # Pellet or Magnet-only capabilities
    servo_config = test_read_servo_config(iface, Target.MAGNET_DEVICE, Motor.MAGNET_SERVO)
    test_write_servo_config(iface, Target.MAGNET_DEVICE, servo_config)
    stepper_config = test_read_stepper_config(iface, Motor.PELLET_X_MOTOR)
    test_write_stepper_config(iface, stepper_config)
    test_write_gpio(iface, True)
    test_write_gpio(iface, False)
    test_tone(iface)
    test_analog_out(iface)
    test_tare_load_cell(iface)
    test_tare_pressure_sensor(iface)
    test_color_led(iface)
    test_streaming_data(iface)

    iface.close()
