import argparse
import logging
import queue
import time
from threading import Thread
from copy import copy

from autotrainer.core import SystemStatusMessageKind
from autotrainer.device import CanDevice, DeviceThread, DeviceThreadMessageKind, \
    HeadFixMessageKind, GymDeviceMessageKind, PelletDeliveryMessageKind, Motor, \
    StepperConfig, ServoConfig, motor_to_str, target_to_str, is_stepper, \
    CompoundMovementFile, MotorConfigurationFile, StepperStatus, ServoStatus

logging.basicConfig(level=logging.INFO)
logging.getLogger("autotrainer").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

msg_queue = queue.Queue()
output_file = None
perf_start = None
perf_count = -1
perf_print = False
print_status = Motor.NONE
positions = {
    PelletDeliveryMessageKind.SET_X: 0,
    PelletDeliveryMessageKind.SET_Y: 0,
    PelletDeliveryMessageKind.SET_Z: 0,
}


def monitor_message_queue():
    global perf_start, perf_count, print_status, positions
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

        elif kind == GymDeviceMessageKind.VERSION:
            print(data)

        elif kind == HeadFixMessageKind.MEASUREMENT:
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

        elif kind == GymDeviceMessageKind.READ_CONFIG:
            if isinstance(data, ServoConfig):
                print(
                    f"SERVO\n"
                    f"- target={target_to_str(data.target)}\n"
                    f"- motor={motor_to_str(data.motor)}\n"
                    f"- max vel={data.maximum_velocity}\n"
                    f"- max accel={data.maximum_acceleration}\n"
                    f"- min pos={data.minimum_position}\n"
                    f"- max pos={data.maximum_position}\n"
                    f"- min pwm={data.minimum_pwm_duration}\n"
                    f"- max pwm={data.maximum_pwm_duration}\n"
                )
            elif isinstance(data, StepperConfig):
                print(f"STEPPER\n"
                      f"- target={target_to_str(data.target)}\n"
                      f"- motor={motor_to_str(data.motor)}\n"
                      f"- max vel={data.maximum_velocity}\n"
                      f"- max accel={data.maximum_acceleration}\n"
                      f"- flip limit orientation={data.flip_limit_orientation}\n"
                      f"- microsteps={data.microsteps}\n"
                      f"- step/rev={data.steps_per_revolution}\n"
                      )

        elif ((kind == SystemStatusMessageKind.PELLET_COVER and
               print_status is Motor.PELLET_COVER_SERVO) or
              (kind == SystemStatusMessageKind.PELLET_LOAD and
               print_status is Motor.PELLET_LOAD_SERVO) or
              (kind == SystemStatusMessageKind.HEAD_MAGNET and
               print_status is Motor.MAGNET_SERVO)):

            # TODO deliver full packet. See can_device at or around line 328
            # assert isinstance(data, ServoStatus)
            print(
                f"SERVO:\n"
                # f"- target={target_to_str(data.target)}\n"
                f"- motor={motor_to_str(print_status)}\n"
                f"- position={data}\n"
            )
            print_status = Motor.NONE
        elif ((kind == SystemStatusMessageKind.PELLET_X and
               print_status is Motor.PELLET_X_MOTOR) or
              (kind == SystemStatusMessageKind.PELLET_Y and
               print_status is Motor.PELLET_Y_MOTOR) or
              (kind == SystemStatusMessageKind.PELLET_Z and
               print_status is Motor.PELLET_Z_MOTOR)):
            # assert isinstance(data, StepperStatus)
            print(
                f"STEPPER:\n"
                # f"target={target_to_str(data.target)}\n"
                f"- motor={motor_to_str(print_status)}\n"
                f"- position={data}\n"
                # f"- limit={data.is_at_limit}\n"
            )
            print_status = Motor.NONE

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
    elif motor_name == 'load':
        return Motor.PELLET_LOAD_SERVO
    elif motor_name == 'cover':
        return Motor.PELLET_COVER_SERVO
    elif motor_name == 'magnet':
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

        resp = input(f"Max Velocity (turns/sec) [{orig_config.maximum_velocity}] = ")
        if resp != '':
            config.maximum_velocity = float(resp)

        resp = input(f"Max Acceleration (turns/sec^2) [{orig_config.maximum_acceleration}]= ")
        if resp != '':
            config.maximum_acceleration = float(resp)

        resp = input(f"Flip Limit Location [0, 1] [{orig_config.flip_limit_orientation}]= ")
        if resp != '':
            config.flip_limit_orientation = int(resp) == 1

        resp = input(f"Microsteps [2,4,8,16,32,64] [{orig_config.microsteps}]= ")
        if resp != '':
            config.microsteps = int(resp)

        resp = input(f"Steps/Revolution [{orig_config.steps_per_revolution}]= ")
        if resp != '':
            config.steps_per_revolution = float(resp)

        device_thread.send_message(GymDeviceMessageKind.WRITE_CONFIG, (motor, config))
    else:
        assert isinstance(orig_config, ServoConfig)

        config = copy(orig_config)

        resp = input(f"Max Velocity (deg/sec) [{orig_config.maximum_velocity}]= ")
        if resp != '':
            config.maximum_velocity = float(resp)

        resp = input(f"Max Acceleration (deg/sec^2) [{orig_config.maximum_acceleration}]= ")
        if resp != '':
            config.maximum_acceleration = float(resp)

        resp = input(f"Min Position (deg) [{orig_config.minimum_position}]= ")
        if resp != '':
            config.minimum_position = float(resp)

        resp = input(f"Max Position (deg) [{orig_config.maximum_position}]= ")
        if resp != '':
            config.maximum_position = float(resp)

        resp = input(f"Min PWM Duration (usec) [{orig_config.minimum_pwm_duration}]= ")
        if resp != '':
            config.minimum_pwm_duration = float(resp)

        resp = input(f"Max PWM Duration (usec) [{orig_config.maximum_pwm_duration}]= ")
        if resp != '':
            config.maximum_pwm_duration = float(resp)

        device_thread.send_message(GymDeviceMessageKind.WRITE_CONFIG, (motor, config))


def wait_for_move(kind, position):
    now = time.time()

    while time.time() - now < 2:
        return position >= positions[kind] - 0.1 or position <= positions[kind] + 0.1

    return None


def round_trip_test(motor: Motor, trips: int, device_thread):
    global print_status, positions

    kind = None

    if motor is Motor.PELLET_X_MOTOR:
        kind = PelletDeliveryMessageKind.SET_X
    elif motor is Motor.PELLET_Y_MOTOR:
        kind = PelletDeliveryMessageKind.SET_Y
    elif motor is Motor.PELLET_Z_MOTOR:
        kind = PelletDeliveryMessageKind.SET_Z

    if kind is None:
        print("Test only supports Stepper Motors")
        return

    for i in range(trips):
        device_thread.send_message(kind, data=10)
        time.sleep(2)
        print_status = motor
        time.sleep(1)

        device_thread.send_message(kind, data=0)
        time.sleep(2)
        print_status = motor
        time.sleep(1)


def run_monitor():
    global perf_count
    global print_status

    device = CanDevice()
    device_thread = DeviceThread(device, device._interface, msg_queue)

    device_thread.start()

    mon_thread = Thread(target=monitor_message_queue)

    mon_thread.start()

    device_thread.send_message(DeviceThreadMessageKind.CONNECT)

    while True:
        if perf_count <= 0:
            time.sleep(1)
            line = []
            while len(line) == 0:
                line = input("Enter command (?=help): ").split()

            cmd = line[0]
            params = line[1:]

            if cmd == 'q':
                device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
                msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
                break
            elif cmd == '?':
                print("?                  ::help")
                print("a <motor>          ::Read Configuration")
                print("b <motor>          ::Write Configuration")
                print("c                  ::Cover Pellet")
                print("d <freq> <period>  ::Tone (hz, sec)")
                print("e <motor> <trips>  ::Stepper round trip test")
                print("f <file>           ::Load Motor Configuration")
                print("F <file>           ::Load Compound Movement Configuration")
                print("h                  ::Home Position")
                print("l                  ::Load Pellet")
                print("m <pos>            ::Move Magnet Servo [0:120] (deg)")
                print("n <pos>            ::Move Load Servo [0:120] (deg)")
                print("o <pos>            ::Move Cover Servo [0:120] (deg)")
                print("q                  ::Quit")
                print("r                  ::Release Pellet")
                print("s                  ::Send Pellet")
                print("t                  ::Tare Load Cell/Pressure Sensors")
                print("v                  ::Version (not available yet)")
                print("w <motor>          ::Motor Status")
                print("x <pos>            ::Move X [0:12] (turns)")
                print("y <pos>            ::Move Y [0:12] (turns)")
                print("z <pos>            ::Move Z [0:12] (turns)")
                print("X                  ::Home X to Limit")
                print("Y                  ::Home Y to Limit")
                print("Z                  ::Home Z to Limit")
                print()
                print("<motor> is one of [x, y, z, load, cover, magnet]")

            elif cmd == 'a':
                device_thread.send_message(GymDeviceMessageKind.READ_CONFIG,
                                           str_to_motor(params[0]))
            elif cmd == 'b':
                write_config(str_to_motor(params[0]), device_thread)
            elif cmd == 'c':
                device_thread.send_message(PelletDeliveryMessageKind.COVER_PELLET)
            elif cmd == 'd':
                device_thread.send_message(PelletDeliveryMessageKind.PLAY_TONE,
                                           # period from sec to msec
                                           data=(int(params[0]), int(params[1]) * 1000))
            elif cmd == 'e':
                round_trip_test(str_to_motor(params[0]), int(params[1]), device_thread)
            elif cmd == 'f':
                file = MotorConfigurationFile(params[0])
                device_thread.use_motor_configurations(file)
            elif cmd == 'F':
                file = CompoundMovementFile(params[0])
                device_thread.use_compound_movements(file)
            elif cmd == 'h':
                device_thread.send_message(PelletDeliveryMessageKind.SEND_HOME)
            elif cmd == 'l':
                device_thread.send_message(PelletDeliveryMessageKind.LOAD_PELLET)
            elif cmd == 'm':
                device_thread.send_message(HeadFixMessageKind.SET_MAGNET_INTENSITY,
                                           data=float(params[0]))
            elif cmd == 'n':
                device_thread.send_message(PelletDeliveryMessageKind.SET_LOAD_SERVO,
                                           data=float(params[0]))
            elif cmd == 'o':
                device_thread.send_message(PelletDeliveryMessageKind.SET_COVER_SERVO,
                                           data=float(params[0]))
            elif cmd == 'r':
                device_thread.send_message(PelletDeliveryMessageKind.RELEASE_PELLET)
            elif cmd == 's':
                device_thread.send_message(PelletDeliveryMessageKind.SEND_PELLET)
            elif cmd == 't':
                device_thread.send_message(HeadFixMessageKind.UPDATE_SCALE_TARE)
            elif cmd == 'v':
                device_thread.send_message(GymDeviceMessageKind.VERSION)
            elif cmd == 'w':
                print_status = str_to_motor(params[0])
            elif cmd == 'x':
                device_thread.send_message(PelletDeliveryMessageKind.SET_X,
                                           data=float(params[0]))
            elif cmd == 'y':
                device_thread.send_message(PelletDeliveryMessageKind.SET_Y,
                                           data=float(params[0]))
            elif cmd == 'z':
                device_thread.send_message(PelletDeliveryMessageKind.SET_Z,
                                           data=float(params[0]))
            elif cmd == 'X':
                device_thread.send_message(PelletDeliveryMessageKind.SEND_TO_LIMITS,
                                           data=Motor.PELLET_X_MOTOR)
            elif cmd == 'Y':
                device_thread.send_message(PelletDeliveryMessageKind.SEND_TO_LIMITS,
                                           data=Motor.PELLET_Y_MOTOR)
            elif cmd == 'Z':
                device_thread.send_message(PelletDeliveryMessageKind.SEND_TO_LIMITS,
                                           data=Motor.PELLET_Z_MOTOR)
        else:
            if not mon_thread.is_alive():
                device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
                break
            else:
                time.sleep(0.1)

    logger.info("waiting for device thread to terminate")

    device_thread.join()

    logger.info("done")


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
