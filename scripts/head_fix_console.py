import argparse
import logging
import queue
import time
from threading import Thread

from autotrainer.core import SystemStatusMessageKind, SystemCommandKind
from autotrainer.device import HeadFix
from autotrainer.device import DeviceConnection

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

msg_queue = queue.Queue()

output_file = None

perf_start = None

perf_count = -1

monitor_active = True


def monitor_message_queue():
    global perf_start, perf_count, monitor_active
    logger.info("starting message queue thread")

    measurement_count = 0

    perf_end = None

    output_fd = None

    if output_file is not None:
        output_fd = open(output_file, 'w')
        output_fd.write("Index, Weight, Switch, Pressure, Temperature, Humidity\n")

    while monitor_active:
        try:
            msg = msg_queue.get_nowait()
        except queue.Empty:
            time.sleep(0.001)
            continue

        try:
            if msg[0] == SystemStatusMessageKind.MEASUREMENT and output_fd is not None:
                if perf_start is None:
                    perf_start = time.perf_counter_ns()
                for measurement in msg[1]:
                    output_fd.write(f"{measurement.weight}, {measurement.switch}, {measurement.pressure},"
                                    f"{measurement.temperature}, {measurement.humidity}\n")

                measurement_count += len(msg[1])

                if 0 < perf_count <= measurement_count:
                    perf_end = time.perf_counter_ns()
                    break
        except Exception as err:
            logger.warning("Error executing msg %r: %s", msg, err)

    if output_fd is not None:
        output_fd.close()

    if perf_count > 0 and perf_start is not None:
        logger.info(f"{perf_count} samples at {(1.0e9 * perf_count) / (perf_end - perf_start)} samples/s")


def run_monitor(port: str, timeout: int):
    global perf_count, monitor_active

    mon_thread = Thread(target=monitor_message_queue)

    mon_thread.start()

    device_connection = DeviceConnection(HeadFix(port), msg_queue)

    device_connection.request_connect()

    while True:
        if timeout > 0:
            # Run for the request time and exit.  Primarily supports automated testing by ensuring can launch and close
            # cleanly.
            time.sleep(timeout)
            device_connection.request_disconnect()
            logger.debug("timeout reached, terminating")
            break
        elif perf_count <= 0:
            # Interactive mode.
            cmd = input("Enter command: ")

            if cmd.startswith("q"):
                device_connection.request_disconnect()
                break
            elif cmd.startswith("A"):
                device_connection.send_message(SystemCommandKind.RAW_COMMAND, cmd + "x")
            elif cmd.startswith("O"):
                device_connection.send_message(SystemCommandKind.SETTINGS)
            elif cmd.startswith("F"):
                device_connection.send_message(SystemCommandKind.REQUEST_VERSION)
            elif cmd.startswith("M"):
                device_connection.send_message(SystemCommandKind.UPDATE_SCALE_TARE)
            elif cmd.startswith("S"):
                device_connection.send_message(SystemCommandKind.STREAM_START)
            elif cmd.startswith("T"):
                device_connection.send_message(SystemCommandKind.STREAM_STOP)
        else:
            # Perform performance calculation and exit.
            if not mon_thread.is_alive():
                device_connection.request_disconnect()
                break
            else:
                time.sleep(0.1)

    monitor_active = False

    mon_thread.join()

    logger.info("waiting for device thread to terminate")

    device_connection.join()

    logger.info("done")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")
    parser.add_argument("-o", "--output", help="and output file to record measurements")
    parser.add_argument("-p", "--perf",
                        help="performance measurement with specified number of samples",
                        type=int, default=-1)
    parser.add_argument("-t", "--timeout", help="run for the specified number of seconds and exit",
                        type=int, default=0)

    args = parser.parse_args()

    output_file = args.output

    perf_count = args.perf

    run_monitor(args.port, args.timeout)
