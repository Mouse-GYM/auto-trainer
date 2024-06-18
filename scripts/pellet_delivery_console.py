import argparse
import logging

from autotrainer.device import SerialInterface, GymDeviceMessageKind
from autotrainer.device import PelletDelivery, PelletDeliveryMessageKind
from autotrainer.device import DeviceThread, DeviceThreadMessageKind

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


def message_queue_callback(kind, context):
    if PelletDeliveryMessageKind.is_member(kind):
        logger.info(f"device-message {PelletDeliveryMessageKind(kind).name}: {context}")
    elif GymDeviceMessageKind.is_member(kind):
        logger.info(f"device-message {GymDeviceMessageKind(kind).name}: {context}")
    else:
        logger.info(f"device-message {kind}: {context}")


def run_monitor(port: str):
    device_interface = SerialInterface(port)

    pellet_delivery = PelletDelivery()

    device_thread = DeviceThread(pellet_delivery, device_interface, message_callback=message_queue_callback)

    device_thread.start()

    device_thread.send_message(DeviceThreadMessageKind.CONNECT)

    while True:
        cmd = input("Enter command: ")

        if cmd.startswith("q"):
            device_thread.send_message(DeviceThreadMessageKind.TERMINATE)
            break
        else:
            device_thread.send_message(PelletDeliveryMessageKind.RAW_COMMAND, cmd + "x")

    logger.info("waiting for device thread to terminate")

    device_thread.join()

    logger.info("done")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")

    args = parser.parse_args()

    run_monitor(args.port)
