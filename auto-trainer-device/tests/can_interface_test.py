"""Assumes/requires real hardware is available and actively sending messages of some sort."""
import time
import pytest
from torch.jit import interface

from autotrainer.device import (CanInterface, Target, Motor, Heartbeat, ServoConfig, StepperConfig,
                                DigitalOutputs, MagnetDigitalInputs, PelletDigitalInputs, Tone,
                                AnalogOutputs, AnalogOutput, LoadCellReading, PressureReading,
                                ColorLed, AudioData, DoorData, ServoStatus, StepperStatus,
                                SensorStatus)


@pytest.mark.canbus
def test_connect():
    interface = CanInterface()

    assert interface.open()

    tries = 0
    while not interface.are_addresses_valid() and tries < 100:
        msgs = interface.read(20)
        tries += 1

    assert interface.are_addresses_valid()

    return interface


@pytest.mark.canbus
def test_heartbeat(interface: CanInterface, target: Target):
    """Verify ping"""
    assert interface.send_heartbeat()

    heartbeat = interface.get_response(Heartbeat, target, 2)

    assert heartbeat is not None


@pytest.mark.canbus
def test_read_config(interface: CanInterface, motor: Motor):
    target = CanInterface.target_of_motor(motor)

    """Verify servo configuration can be read"""
    assert interface.request_motor_config(motor)

    config = interface.get_response(
        ServoConfig if interface.is_servo(motor) else StepperConfig,
        target)
    assert config is not None
    assert config.motor is motor

    return config


@pytest.mark.canbus
def test_write_servo_config(interface: CanInterface, config: ServoConfig):
    """Verify servo configuration can be written"""
    orig_min = config.min_position
    orig_max = config.max_position

    config.min_position -= 10
    config.max_position += 10
    assert interface.write_servo_config(config)

    new_config = test_read_config(interface, config.motor)
    assert new_config.min_position == config.min_position
    assert new_config.max_position == config.max_position

    config.min_position = orig_min
    config.max_position = orig_max

    assert interface.write_servo_config(config)


def write_stepper_config(interface: CanInterface, config: StepperConfig) -> bool:
    if not interface.write_stepper_config(config):
        return False

    new_config = test_read_config(interface, config.motor)

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
    data = interface.get_response(PelletDigitalInputs, target, 2.0)
    assert data is not None
    return data


@pytest.mark.canbus
def test_tone(interface: CanInterface):
    frequency_hz = 2000
    duration_ms = 400
    assert interface.emit_tone(frequency_hz, duration_ms);

    # give it a chance to update
    tone = None
    for retry in range(3):
        tone = interface.get_response(Tone, Target.PELLET_DEVICE)
    assert tone is not None
    # assert tone.frequency_hz == frequency_hz
    assert tone.time_remaining_ms <= duration_ms


@pytest.mark.canbus
def test_analog_out(interface: CanInterface):
    value_mv = 1000
    assert interface.set_analog_output(AnalogOutputs.STATUS_OUT, value_mv);

    aout = interface.get_response(AnalogOutput, Target.PELLET_DEVICE)
    assert aout is not None
    # assert aout.status_out_mv == value_mv


@pytest.mark.canbus
def test_tare_load_cell(interface: CanInterface):
    assert interface.tare_load_cell();

    for tries in range(3):
        loadcell = interface.get_response(LoadCellReading, Target.MAGNET_DEVICE)
        assert loadcell is not None
        if loadcell.load_mv <= 0.01:
            return

    assert False


@pytest.mark.canbus
def test_tare_pressure_sensor(interface: CanInterface):
    assert interface.tare_pressure_sensor();

    for tries in range(3):
        pressure = interface.get_response(PressureReading, Target.MAGNET_DEVICE)
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
        led = interface.get_response(ColorLed, Target.PELLET_DEVICE)
    assert led is not None
    assert led.red == red
    assert led.green == green
    assert led.blue == blue


def test_streaming_data(interface: CanInterface):
    audio = interface.get_response(AudioData, Target.PELLET_DEVICE, 3.0)
    assert audio is None or len(audio.magnitudes) == 32

    door = interface.get_response(DoorData, Target.PELLET_DEVICE)
    assert door is not None
    assert len(door.open_state) == 3

    status = interface.get_response(ServoStatus, Target.PELLET_DEVICE)
    assert status is not None

    status = interface.get_response(ServoStatus, Target.MAGNET_DEVICE)
    assert status is not None

    status = interface.get_response(StepperStatus, Target.PELLET_DEVICE)
    assert status is not None

    status = interface.get_response(SensorStatus, Target.MAGNET_DEVICE)
    assert status is not None


def test_stepper_home(interface: CanInterface):
    assert interface.stepper_home(Motor.PELLET_X_MOTOR)
    time.sleep(1)
    assert interface.stepper_home(Motor.PELLET_Y_MOTOR)
    time.sleep(1)
    assert interface.stepper_home(Motor.PELLET_Z_MOTOR)
    time.sleep(1)


if __name__ == '__main__':
    iface = test_connect()

    # test_heartbeat(iface, Target.PELLET_DEVICE)
    # test_heartbeat(iface, Target.MAGNET_DEVICE)

    # Pellet or Magnet-only capabilities
    servo_config = test_read_config(iface, Motor.MAGNET_SERVO)
    test_write_servo_config(iface, servo_config)
    stepper_config = test_read_config(iface, Motor.PELLET_X_MOTOR)
    test_write_stepper_config(iface, stepper_config)
    test_write_gpio(iface, True)
    test_write_gpio(iface, False)
    test_tone(iface)
    test_analog_out(iface)
    # test_tare_load_cell(iface)
    # test_tare_pressure_sensor(iface)
    test_color_led(iface)
    test_streaming_data(iface)

    iface.close()
