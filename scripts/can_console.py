import argparse
import logging
import queue
import time
from threading import Thread
from copy import copy
from enum import IntEnum

from autotrainer.core import SystemStatusMessageKind, SystemCommandKind
from autotrainer.device import CanDevice, DeviceConnection, DeviceThreadMessageKind, Motor, \
    StepperConfig, ServoConfig, motor_to_str, target_to_str, is_stepper, \
    CompoundMovementFile, MotorConfigurationFile

logging.basicConfig(level=logging.INFO)
logging.getLogger("autotrainer").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

msg_queue = queue.Queue()
output_file = None
perf_start = None
perf_count = -1
perf_print = False
print_motor_status = Motor.NONE
print_status = None
positions = {
    SystemCommandKind.SET_X: 0,
    SystemCommandKind.SET_Y: 0,
    SystemCommandKind.SET_Z: 0,
}
get_input = True


class StatusType(IntEnum):
    FRONT_DOOR = 1,
    DRAWER_DOOR = 2,
    SENSORS = 3,
    STIMULUS = 4,


def monitor_message_queue():
    global perf_start, perf_count, print_motor_status, positions, print_status
    global get_input

    logger.info("starting message queue thread")

    measurement_count = 0

    perf_end = None

    output_fd = None

    if output_file is not None:
        output_fd = open(output_file, 'w')
        output_fd.write("Time, Index, Weight, Switch, Pressure, Temperature, Humidity\n")

    next_heartbeat = 500

    while True:
        kind, data = msg_queue.get()

        if kind == DeviceThreadMessageKind.TERMINATE:
            break

        elif kind == SystemStatusMessageKind.ACKNOWLEDGE:
            get_input = True

        elif kind == SystemStatusMessageKind.FIRMWARE_VERSION:
            print(data)
            get_input = True

        elif kind == SystemStatusMessageKind.MEASUREMENTS:
            if print_status is StatusType.SENSORS:
                d = data[0]
                print(f"- Head Detect:     {d.switch}")
                print(f"- Load Weight (v): {d.weight:.3f}")
                print(f"- Pressure (v):    {d.pressure:.3f}")
                print(f"- Temperature (F): {d.temperature:.1f}")
                print(f"- Humidity (%):    {d.humidity:.1f}")
                print_status = StatusType.DRAWER_DOOR

            if perf_start is None:
                perf_start = time.perf_counter_ns()

            if output_fd is not None:
                for d in data:
                    output_fd.write(
                        f"{d.when}, {d.timestamp}, {d.weight}, "
                        f" {d.switch},"
                        f" {d.pressure},"
                        f" {d.temperature}, {d.humidity}\n")

            measurement_count += len(data)

            if measurement_count > next_heartbeat:
                if perf_print:
                    logger.info(
                        f"{measurement_count} samples at {(1.0e9 * measurement_count) / (time.perf_counter_ns() - perf_start)} samples/s")
                next_heartbeat += 500

            if 0 < perf_count <= measurement_count:
                perf_end = time.perf_counter_ns()
                break

        elif kind == SystemStatusMessageKind.MOTOR_CONFIGURATION:
            if isinstance(data, ServoConfig):
                print(
                    f"SERVO\n"
                    f"- target={target_to_str(data.target)}\n"
                    f"- motor={motor_to_str(data.motor)}\n"
                    f"- max vel (deg/sec)={data.maximum_velocity:.2f}\n"
                    f"- max accel (deg/sec^2)={data.maximum_acceleration:.2f}\n"
                    f"- min pos (deg)={data.minimum_position:.1f}\n"
                    f"- max pos (deg)={data.maximum_position:.1f}\n"
                    f"- min pwm={data.minimum_pwm_duration:.1f}\n"
                    f"- max pwm={data.maximum_pwm_duration:.1f}\n"
                )
            elif isinstance(data, StepperConfig):
                print(f"STEPPER\n"
                      f"- target={target_to_str(data.target)}\n"
                      f"- motor={motor_to_str(data.motor)}\n"
                      f"- max vel (mm/sec)={data.maximum_velocity:.2f}\n"
                      f"- max accel (mm/sec^2)={data.maximum_acceleration:.2f}\n"
                      f"- flip limit orientation={data.flip_limit_orientation}\n"
                      f"- microsteps={data.microsteps}\n"
                      f"- step/rev={data.steps_per_revolution:.0f}\n"
                      )
            get_input = True

        elif ((kind == SystemStatusMessageKind.PELLET_COVER and
               print_motor_status is Motor.PELLET_COVER_SERVO) or
              (kind == SystemStatusMessageKind.PELLET_LOAD and
               print_motor_status is Motor.PELLET_LOAD_SERVO) or
              (kind == SystemStatusMessageKind.HEAD_MAGNET and
               print_motor_status is Motor.MAGNET_SERVO)):

            # TODO deliver full packet. See can_device at or around line 328
            # assert isinstance(data, ServoStatus)
            print(
                f"SERVO:\n"
                # f"- target={target_to_str(data.target)}\n"
                f"- motor={motor_to_str(print_motor_status)}\n"
                f"- position (deg)={data:.2f}\n"
            )
            print_motor_status = Motor.NONE
            get_input = True
        elif ((kind == SystemStatusMessageKind.PELLET_X and
               print_motor_status is Motor.PELLET_X_MOTOR) or
              (kind == SystemStatusMessageKind.PELLET_Y and
               print_motor_status is Motor.PELLET_Y_MOTOR) or
              (kind == SystemStatusMessageKind.PELLET_Z and
               print_motor_status is Motor.PELLET_Z_MOTOR)):
            # assert isinstance(data, StepperStatus)
            print(
                f"STEPPER:\n"
                # f"target={target_to_str(data.target)}\n"
                f"- motor={motor_to_str(print_motor_status)}\n"
                f"- position (mm) ={data:.2f}\n"
                # f"- limit={data.is_at_limit}\n"
            )
            print_motor_status = Motor.NONE
            get_input = True

        elif kind == SystemStatusMessageKind.DRAWER_DOOR:
            if print_status is StatusType.DRAWER_DOOR:
                print(f"- Drawer Door:     {'Open' if data else 'Closed'}")
                print_status = StatusType.FRONT_DOOR

        elif kind == SystemStatusMessageKind.FRONT_DOOR:
            if print_status is StatusType.FRONT_DOOR:
                print(f"- Front Door:      {'Open' if data else 'Closed'}")
                print_status = StatusType.STIMULUS

        elif kind == SystemStatusMessageKind.STIMULUS_INPUTS:
            if print_status is StatusType.STIMULUS:
                for i in range(4):
                    print(f"- Stimulus #{i + 1}:     {data[i]}")
                print_status = None
                get_input = True

        if kind == SystemStatusMessageKind.PELLET_X or \
            kind == SystemStatusMessageKind.PELLET_Y or \
            kind == SystemStatusMessageKind.PELLET_Z:
            positions[kind] = int(data)

    if output_fd is not None:
        output_fd.close()

    if perf_print and perf_count > 0 and perf_start is not None:
        logger.info(
            f"{perf_count} samples at {(1.0e9 * perf_count) / (perf_end - perf_start)} samples/s")


def str_to_motor(motor_name: str):
    if motor_name == 'x':
        return Motor.PELLET_X_MOTOR
    elif motor_name == 'y':
        return Motor.PELLET_Y_MOTOR
    elif motor_name == 'z':
        return Motor.PELLET_Z_MOTOR
    elif motor_name == 'load' or motor_name == 'l':
        return Motor.PELLET_LOAD_SERVO
    elif motor_name == 'cover' or motor_name == 'c':
        return Motor.PELLET_COVER_SERVO
    elif motor_name == 'magnet' or motor_name == 'm':
        return Motor.MAGNET_SERVO
    else:
        return None


def write_config(motor: Motor, device_thread):
    if motor is None:
        return

    orig_config = device_thread._interface.get_motor_configuration(motor)

    if is_stepper(motor):
        assert isinstance(orig_config, StepperConfig)
        config = copy(orig_config)

        resp = input(f"Max Velocity (mm/sec) [{orig_config.maximum_velocity:.2f}] = ")
        if resp != '':
            config.maximum_velocity = float(resp)

        resp = input(f"Max Acceleration (mm/sec^2) [{orig_config.maximum_acceleration:.2f}]= ")
        if resp != '':
            config.maximum_acceleration = float(resp)

        resp = input(f"Flip Limit Location [0, 1] [{orig_config.flip_limit_orientation}]= ")
        if resp != '':
            config.flip_limit_orientation = int(resp) == 1

        resp = input(f"Microsteps [2,4,8,16,32,64] [{orig_config.microsteps}]= ")
        if resp != '':
            config.microsteps = int(resp)

        resp = input(f"Steps/Revolution [{orig_config.steps_per_revolution:.0f}]= ")
        if resp != '':
            config.steps_per_revolution = float(resp)

        device_thread.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, (motor, config))
    else:
        assert isinstance(orig_config, ServoConfig)

        config = copy(orig_config)

        resp = input(f"Max Velocity (deg/sec) [{orig_config.maximum_velocity:.2f}]= ")
        if resp != '':
            config.maximum_velocity = float(resp)

        resp = input(f"Max Acceleration (deg/sec^2) [{orig_config.maximum_acceleration:.2f}]= ")
        if resp != '':
            config.maximum_acceleration = float(resp)

        resp = input(f"Min Position (deg) [{orig_config.minimum_position:.1f}]= ")
        if resp != '':
            config.minimum_position = float(resp)

        resp = input(f"Max Position (deg) [{orig_config.maximum_position:.1f}]= ")
        if resp != '':
            config.maximum_position = float(resp)

        resp = input(f"Min PWM Duration (usec) [{orig_config.minimum_pwm_duration:.1f}]= ")
        if resp != '':
            config.minimum_pwm_duration = float(resp)

        resp = input(f"Max PWM Duration (usec) [{orig_config.maximum_pwm_duration:.1f}]= ")
        if resp != '':
            config.maximum_pwm_duration = float(resp)

        device_thread.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, (motor, config))


def wait_for_move(kind, position):
    now = time.time()

    while time.time() - now < 2:
        return position >= positions[kind] - 0.1 or position <= positions[kind] + 0.1

    return None


def round_trip_test(motor: Motor, trips: int, device_thread):
    global print_motor_status, positions

    cmd = motor_to_set_command[motor]

    for i in range(trips):
        device_thread.send_message(cmd, data=22.0 if is_stepper(motor) else 100)  # in mm or deg
        time.sleep(2)
        print_motor_status = motor
        time.sleep(1)

        device_thread.send_message(cmd, data=0)
        time.sleep(2)
        print_motor_status = motor
        time.sleep(1)


# Generate either just a position value or a tuple of (position, rate)
def move_parameter(params):
    if len(params) == 1:
        return float(params[0])
    else:
        return float(params[0]), float(params[1])


def run_monitor():
    global get_input
    global perf_count
    global print_motor_status
    global print_status

    device_thread = DeviceConnection(CanDevice(), msg_queue)

    device_thread.start()

    mon_thread = Thread(target=monitor_message_queue)

    mon_thread.start()

    device_thread.send_message(DeviceThreadMessageKind.CONNECT)

    while True:
        if perf_count <= 0:
            while not get_input:
                time.sleep(0.1)
            get_input = False
            line = []
            while len(line) == 0:
                line = input("Enter command (?=help): ").split()

            cmd = line[0]
            params = line[1:]

            motor = str_to_motor(cmd)

            # 'a' - audio
            # 'c' - cover servo
            # 'f' - load-from-files
            # 'h' - help
            # 'l' - load servo
            # 'm' - magnet servo
            # 'o' - set output
            # 'p' - pellet move commands
            # 'r' - RGB LED
            # 's' - System status
            # 't' - Tare scales
            # 'v' - version
            # 'x' - x motor
            # 'y' - y motor
            # 'z' - z motor
            try:
                if cmd == '?':
                    print_help()
                    get_input = True

                elif motor is not None:
                    handle_motor_command(motor, params, device_thread)

                elif cmd == 'a' or cmd == 'audio':
                    device_thread.send_message(SystemCommandKind.PLAY_TONE,
                                               # period from sec to msec
                                               data=(int(params[0]), int(float(params[1]) * 1000)))

                elif cmd == 'd' or cmd == 'delay':
                    device_thread.send_message(SystemCommandKind.DELAY, float(params[0]))

                elif cmd == 'f' or cmd == 'file':
                    if params[0] == 'motor':
                        file = MotorConfigurationFile(params[1])
                        device_thread.use_motor_configurations(file)
                    elif cmd == 'move':
                        file = CompoundMovementFile(params[1])
                        device_thread.use_compound_movements(file)
                    else:
                        print(f"Unknown file request: {params[0]}")
                    get_input = True

                elif cmd == 'g' or cmd == 'go':
                    device_thread.send_message(SystemCommandKind.SEND_FIXED_XYZ)

                elif cmd == 'h' or cmd == 'home':
                    device_thread.send_message(SystemCommandKind.SEND_HOME)

                elif cmd == 'o' or cmd == 'output':
                    handle_output_command(params, device_thread)

                elif cmd == 'p' or cmd == 'pellet':
                    handle_pellet_command(params, device_thread)

                elif cmd == 'q' or cmd == 'quit':
                    device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
                    msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
                    break

                elif cmd == 'r' or cmd == 'rgb':
                    device_thread.send_message(SystemCommandKind.SET_RGB_LED,
                                               (int(params[0]), int(params[1]), int(params[2])))

                elif cmd == 's' or cmd == 'status':
                    print_status = StatusType.SENSORS

                elif cmd == 't' or cmd == 'tare':
                    device_thread.send_message(SystemCommandKind.UPDATE_SCALE_TARE)

                elif cmd == 'v' or cmd == 'version':
                    device_thread.send_message(SystemCommandKind.REQUEST_VERSION)

            except ValueError:
                print("Invalid numeric value in command")
                get_input = True
            except IndexError:
                print(f"Invalid command: {cmd} {params}")
                get_input = True
        else:
            if not mon_thread.is_alive():
                device_thread.request_terminate()
                break
            else:
                time.sleep(0.1)

    logger.info("waiting for device thread to terminate")

    device_thread.join()

    logger.info("done")


motor_to_set_command = {
    Motor.PELLET_X_MOTOR: SystemCommandKind.SET_X,
    Motor.PELLET_Y_MOTOR: SystemCommandKind.SET_Y,
    Motor.PELLET_Z_MOTOR: SystemCommandKind.SET_Z,
    Motor.MAGNET_SERVO: SystemCommandKind.SET_MAGNET_INTENSITY,
    Motor.PELLET_COVER_SERVO: SystemCommandKind.SET_COVER_SERVO,
    Motor.PELLET_LOAD_SERVO: SystemCommandKind.SET_LOAD_SERVO
}


def handle_motor_command(motor: Motor, params, device_thread):
    global print_motor_status, get_input
    try:
        float(params[0])
        numeric = True
    except ValueError:
        numeric = False
    except IndexError:
        numeric = False

    # query stepper status
    if len(params) == 0:
        print_motor_status = motor

    # set position
    elif params[0] == 'set':
        device_thread.send_message(motor_to_set_command[motor],
                                   data=move_parameter(params[1:]))

    # set position (no 'set')
    elif numeric:
        device_thread.send_message(motor_to_set_command[motor],
                                   data=move_parameter(params[0:]))

    # sent to home position
    elif params[0] == 'home':
        device_thread.send_message(SystemCommandKind.SEND_TO_LIMITS, data=motor)

    elif params[0] == 'trip':
        round_trip_test(motor, int(params[1]), device_thread)
        get_input = True

    # read or write configuration
    elif params[0] == 'config':
        if params[1] == 'read':
            device_thread.send_message(SystemCommandKind.READ_MOTOR_CONFIGURATION, data=motor)
        elif params[1] == 'write':
            write_config(motor, device_thread)
        else:
            print(f"Unrecognized configuration request: {params[1]}")
            get_input = True

    elif params[0] == 'step':
        start = int(params[1])
        stop = int(params[2])
        step = int(params[3]) if len(params) > 3 else 1

        for position in range(start, stop, step if start < stop else -step):
            device_thread.send_message(motor_to_set_command[motor],
                                       data=float(position))
            time.sleep(1 + .25 * step)
        get_input = True
    else:
        print(f"Unrecognized motor command: {params[0]}")
        get_input = True


def handle_pellet_command(params, device_thread):
    global get_input
    """
    Handle a pellet control sequence
    """
    cmd = params[0]

    if cmd == 'cover' or cmd == 'c':
        device_thread.send_message(SystemCommandKind.COVER_PELLET)
    elif cmd == 'load' or cmd == 'l':
        device_thread.send_message(SystemCommandKind.LOAD_PELLET)
    elif cmd == 'release' or cmd == 'r':
        device_thread.send_message(SystemCommandKind.RELEASE_PELLET)
    elif cmd == 'send' or cmd == 's':
        device_thread.send_message(SystemCommandKind.SEND_PELLET)
    else:
        print(f"Unrecognized pellet command: {cmd}")
        get_input = True


def handle_output_command(params, device_thread):
    cmd = params[0]

    if cmd == 'd' or cmd == 'digital':
        device_thread.send_message(SystemCommandKind.SET_DIGITAL_OUTPUT,
                                   (int(params[1]), int(params[2])))
    elif cmd == 'a' or cmd == 'analog':
        device_thread.send_message(SystemCommandKind.SET_ANALOG_OUTPUT,
                                   (int(params[1]), int(params[2])))


def print_help():
    print("?                                  "
          " ::help")
    print("For the commands, you can either use the letter or full command name (e.g. q or quit)\n")

    print("<motor>                            "
          " ::Motor status")
    print("<motor> [set] <pos> [<rate>]       "
          " ::Move servo pos [0:120] (deg) rate [0:100] (%)\n"
          "                                   "
          " ::Move stepper pos [0:27] (mm) rate [0:100] (%)")
    print("<motor> step <start> <end> [<step>]"
          " ::Step degrees or mms at a time")
    print("<motor> config read                "
          " ::Read Configuration")
    print("<motor> config write               "
          " ::Write Configuration")
    print("<motor> trip <cnt>                 "
          " ::<cnt> Round trips")
    print("<motor> is one of: x, y, z, l[oad], c[over], m[agnet]")
    print()

    print("p[ellet] c[over]                   "
          " ::Cover Pellet Sequence")
    print("p[ellet] l[oad]                    "
          " ::Load Pellet Sequence")
    print("p[ellet] r[elease]                 "
          " ::Release Pellet Sequence")
    print("p[ellet] s[end]                    "
          " ::Send Pellet Sequence")
    print()

    print("a[udio] <freq> <period>            "
          " ::Audio sound (hz) (sec)")
    print("d[elay] <sec>                      "
          " ::Delay")
    print("g[o]                               "
          " ::Go to Send Position (X, Y, Z)")
    print("h[ome]                             "
          " ::Go to Home Position (0, 0, 0)")
    print("f[ile] motor <file>                "
          " ::Load Motor Configuration")
    print("f[ile] move <file>                 "
          " ::Load Compound Movement Configuration")
    print("o[utput] d[igital] <chan> <state>  "
          " ::Set digital output on pellet chan [1:4] state [0:1]")
    print("o[utput] a[nalog] <chan> <mvolts>  "
          " ::Set analog output on pellet chan [1] mvolts [0:5000]")
    print("q[uit]                             "
          " ::Quit")
    print("r[gb] <red> <green> <blue>         "
          " ::Set RGB LED. Values in %")
    print("s[tatus]                           "
          " ::Show Status")
    print("t[are]                             "
          " ::Tare Load Cell/Pressure Sensors")
    print("v[ersion]                          "
          " ::Version")
    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("can", help="the can id", type=int, default=1)
    parser.add_argument("-o", "--output", help="and output file to record measurements")
    parser.add_argument("-p", "--perf",
                        help="performance measurement with specified number of samples",
                        type=int, default=-1)

    args = parser.parse_args()

    output_file = args.output

    perf_print = perf_count != -1

    run_monitor()
