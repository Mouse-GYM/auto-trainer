import argparse
import logging
import queue
from threading import Thread

from autotrainer.serial_interface import SerialInterface
from autotrainer.pellet_delivery import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device_thread import DeviceThread, DeviceThreadMessageKind

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

msg_queue = queue.Queue()


def monitor_message_queue():
    logger.info("starting message queue thread")

    while True:
        msg = msg_queue.get()

        if msg[0] == DeviceThreadMessageKind.TERMINATE:
            break

        print(msg[1])


def run_monitor(port: str):
    cmd_queue = queue.Queue()

    device_interface = SerialInterface(port)

    pellet_delivery = PelletDelivery(device_interface)

    thread = DeviceThread(pellet_delivery, device_interface, cmd_queue, msg_queue)

    thread.start()

    mon_thread = Thread(target=monitor_message_queue)

    mon_thread.start()

    while True:
        cmd = input("Enter command: ")

        if cmd.startswith("q"):
            cmd_queue.put((DeviceThreadMessageKind.TERMINATE, None))
            msg_queue.put((DeviceThreadMessageKind.TERMINATE, None))
            break
        else:
            cmd_queue.put((PelletDeliveryMessageKind.RAW_COMMAND, cmd + "x"))

    logger.info("waiting for device thread to terminate")

    thread.join()

    logger.info("done")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")

    args = parser.parse_args()

    run_monitor(args.port)
