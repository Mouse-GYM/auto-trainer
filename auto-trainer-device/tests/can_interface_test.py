"""Assumes/requires real hardware is available and actively sending messages of some sort."""
import time
import pytest

pytestmark = pytest.mark.canbus

from autotrainer.device import (CanInterface, Target, Motor, Heartbeat, ServoConfig, StepperConfig,
                                DigitalOutputs, PelletDigitalInputs, Tone,
                                AnalogOutputs, AnalogOutput, LoadCellReading, PressureReading,
                                ColorLed, AudioData, DoorData, ServoStatus, StepperStatus,
                                SensorStatus, target_of_motor, is_servo)


@pytest.fixture
def interface():
    return _connect()


# @pytest.skip(reason="utility method")
def _connect():
    interface = CanInterface()

    assert interface.open()

    tries = 0
    while not interface.are_addresses_valid() and tries < 100:
        interface.read(20)
        tries += 1

    assert interface.are_addresses_valid()

    return interface


@pytest.mark.canbus
def test_heartbeat(interface: CanInterface, target: Target = Target.PELLET_DEVICE):
    """Verify ping"""
    assert interface.send_heartbeat()

    heartbeat = get_response(interface, Heartbeat, target)

    assert heartbeat is not None


def _read_config(interface: CanInterface, motor: Motor):
    target = target_of_motor(motor)

    """Verify servo configuration can be read"""
    assert interface.request_motor_config(motor)

    config = get_response(interface,
                          ServoConfig if is_servo(motor) else StepperConfig,
                          target)

    return config


@pytest.mark.canbus
def test_read_config(interface: CanInterface, motor: Motor = Motor.MAGNET_SERVO):
    config = _read_config(interface, motor)

    assert config is not None
    assert config.motor is motor


@pytest.mark.canbus
def test_write_servo_config(interface: CanInterface, motor: Motor = Motor.MAGNET_SERVO):
    config = _read_config(interface, motor)

    orig_min = config.min_position
    orig_max = config.max_position

    config.min_position -= 10
    config.max_position += 10
    assert interface.write_servo_config(config)

    new_config = _read_config(interface, config.motor)
    assert new_config.min_position == config.min_position
    assert new_config.max_position == config.max_position

    config.min_position = orig_min
    config.max_position = orig_max

    assert interface.write_servo_config(config)


def _write_stepper_config(interface: CanInterface, config: StepperConfig) -> bool:
    if not interface.write_stepper_config(config):
        return False

    new_config = _read_config(interface, config.motor)

    return new_config.min_step_inverse == config.min_step_inverse and \
        new_config.steps_per_revolution == config.steps_per_revolution


@pytest.mark.canbus
def test_write_stepper_config(interface: CanInterface, motor: Motor = Motor.PELLET_Z_MOTOR):
    config = _read_config(interface, motor)

    orig_min = config.min_step_inverse
    orig_steps = config.steps_per_revolution

    config.min_step_inverse *= 2
    config.steps_per_revolution *= 2
    assert _write_stepper_config(interface, config)

    config.min_step_inverse = orig_min
    config.steps_per_revolution = orig_steps
    assert _write_stepper_config(interface, config)


def _write_gpio(interface: CanInterface, state: bool):
    assert interface.set_digital_output(DigitalOutputs.STIMULUS_1, state)

    for tries in range(5):
        data = _read_gpio(interface, Target.PELLET_DEVICE)
        if data is not None and data.stimulus_1 == state:
            assert True
            return

    assert False


@pytest.mark.canbus
def test_write_gpio(interface: CanInterface):
    _write_gpio(interface, True)
    _write_gpio(interface, False)


def _read_gpio(interface: CanInterface, target: Target):
    return get_response(interface, PelletDigitalInputs, target, 2.0)


@pytest.mark.canbus
def test_tone(interface: CanInterface):
    frequency_hz = 2000
    duration_ms = 400
    assert interface.emit_tone(frequency_hz, duration_ms);

    # give it a chance to update
    tone = None
    for retry in range(3):
        tone = get_response(interface, Tone, Target.PELLET_DEVICE)
    assert tone is not None
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
        if loadcell.load_mv <= 0.01:
            return

    assert False


@pytest.mark.canbus
def test_tare_pressure_sensor(interface: CanInterface):
    assert interface.tare_pressure_sensor();

    for tries in range(3):
        pressure = get_response(interface, PressureReading, Target.MAGNET_DEVICE)
        assert pressure is not None
        if pressure.pressure_mv <= 0.01:
            return

    assert False


@pytest.mark.canbus
def test_color_led(interface: CanInterface):
    red = 25
    green = 50
    blue = 75

    assert interface.set_color_led(red, green, blue)
    # Allow the data to catch up with the command
    led = None
    for tries in range(3):
        led = get_response(interface, ColorLed, Target.PELLET_DEVICE)
    assert led is not None
    assert led.red == red
    assert led.green == green
    assert led.blue == blue


@pytest.mark.canbus
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

    status = get_response(interface, SensorStatus, Target.MAGNET_DEVICE)
    assert status is not None


def test_stepper_home(interface: CanInterface):
    assert interface.stepper_home(Motor.PELLET_X_MOTOR)
    time.sleep(1)
    assert interface.stepper_home(Motor.PELLET_Y_MOTOR)
    time.sleep(1)
    assert interface.stepper_home(Motor.PELLET_Z_MOTOR)
    time.sleep(1)


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
    iface = _connect()

    test_heartbeat(iface, Target.PELLET_DEVICE)
    test_heartbeat(iface, Target.MAGNET_DEVICE)

    test_read_config(iface, Motor.MAGNET_SERVO)
    test_write_servo_config(iface, Motor.MAGNET_SERVO)
    test_read_config(iface, Motor.PELLET_X_MOTOR)
    test_write_stepper_config(iface, Motor.PELLET_X_MOTOR)
    test_write_gpio(iface)
    test_tone(iface)
    test_analog_out(iface)
    test_tare_load_cell(iface)
    test_tare_pressure_sensor(iface)
    test_color_led(iface)
    test_streaming_data(iface)
    test_stepper_home(iface)

    iface.close()
