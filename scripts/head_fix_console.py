import argparse
import logging
import queue
from threading import Thread

from autotrainer.serial_interface import SerialInterface
from autotrainer.head_fix import HeadFix, HeadFixMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

msg_queue = queue.Queue()

output_file = None


def monitor_message_queue():
    logger.info("starting message queue thread")

    output_fd = None

    if output_file is not None:
        output_fd = open(output_file, 'w')
        output_fd.write("Weight, Switch, Pressure\n")

    while True:
        msg = msg_queue.get()

        if msg[0] == DeviceThreadMessageKind.TERMINATE:
            break

        if msg[0] == HeadFixMessageKind.MEASUREMENT and output_fd is not None:
            for measurement in msg[1]:
                output_fd.write(f"{measurement.weight}, {measurement.switch}, {measurement.pressure}\n")

    if output_fd is not None:
        output_fd.close()


def run_monitor(port: str):
    cmd_queue = queue.Queue()

    device_interface = SerialInterface(port)

    head_fix = HeadFix(device_interface)

    thread = DeviceThread(head_fix, device_interface, cmd_queue, msg_queue)

    thread.start()

    mon_thread = Thread(target=monitor_message_queue)

    mon_thread.start()

    while True:
        cmd = input("Enter command: ")

        if cmd.startswith("q"):
            cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None))
            msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
            break
        elif cmd.startswith("A"):
            cmd_queue.put((HeadFixMessageKind.SERVO, cmd + "x"))
        elif cmd.startswith("O"):
            cmd_queue.put((HeadFixMessageKind.SETTINGS, "Ox"))

    logger.info("waiting for device thread to terminate")

    thread.join()

    logger.info("done")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")
    parser.add_argument("-o", "--output", help="and output file to record measurements")

    args = parser.parse_args()

    output_file = args.output

    run_monitor(args.port)
