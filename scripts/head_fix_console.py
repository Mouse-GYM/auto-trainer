import argparse
import logging
import queue
import time
from threading import Thread

from autotrainer.device import GymDeviceMessageKind
from autotrainer.device import HeadFix, HeadFixMessageKind
from autotrainer.device import DeviceThread, DeviceApi, DeviceThreadMessageKind

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

msg_queue = queue.Queue()

output_file = None

perf_start = None

perf_count = -1


def monitor_message_queue():
    global perf_start, perf_count
    logger.info("starting message queue thread")

    measurement_count = 0

    perf_end = None

    output_fd = None

    if output_file is not None:
        output_fd = open(output_file, 'w')
        output_fd.write("Index, Weight, Switch, Pressure, Temperature, Humidity\n")

    while True:
        msg = msg_queue.get()

        if msg[0] == DeviceThreadMessageKind.TERMINATE:
            break

        if msg[0] == HeadFixMessageKind.MEASUREMENT and output_fd is not None:
            if perf_start is None:
                perf_start = time.perf_counter_ns()
            for measurement in msg[1]:
                output_fd.write(
                    f"{measurement.weight}, {measurement.switch}, {measurement.pressure},"
                    f"{measurement.temperature}, {measurement.humidity}\n")

            measurement_count += len(msg[1])

            if 0 < perf_count <= measurement_count:
                perf_end = time.perf_counter_ns()
                break

    if output_fd is not None:
        output_fd.close()

    if perf_count > 0 and perf_start is not None:
        logger.info(
            f"{perf_count} samples at {(1.0e9 * perf_count) / (perf_end - perf_start)} samples/s")


def run_monitor(port: str):
    global perf_count

    device_thread = DeviceThread(HeadFix(port, DeviceApi(message_queue=msg_queue)))

    device_thread.start()

    mon_thread = Thread(target=monitor_message_queue)

    mon_thread.start()

    device_thread.send_message(DeviceThreadMessageKind.CONNECT)

    while True:
        if perf_count <= 0:
            cmd = input("Enter command: ")

            if cmd.startswith("q"):
                device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
                msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
                break
            elif cmd.startswith("A"):
                device_thread.send_message(HeadFixMessageKind.RAW_COMMAND, cmd + "x")
            elif cmd.startswith("O"):
                device_thread.send_message(HeadFixMessageKind.SETTINGS)
            elif cmd.startswith("F"):
                device_thread.send_message(GymDeviceMessageKind.VERSION)
            elif cmd.startswith("M"):
                device_thread.send_message(HeadFixMessageKind.UPDATE_SCALE_TARE)
            elif cmd.startswith("S"):
                device_thread.send_message(HeadFixMessageKind.STREAM_START)
            elif cmd.startswith("T"):
                device_thread.send_message(HeadFixMessageKind.STREAM_STOP)
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

    parser.add_argument("port", help="the serial port to use")
    parser.add_argument("-o", "--output", help="and output file to record measurements")
    parser.add_argument("-p", "--perf",
                        help="performance measurement with specified number of samples",
                        type=int, default=-1)

    args = parser.parse_args()

    output_file = args.output

    perf_count = args.perf

    run_monitor(args.port)
