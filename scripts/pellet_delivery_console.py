import argparse
import logging
import time

from autotrainer.device import GymDeviceMessageKind, PelletDeliveryMessageKind
from autotrainer.device import PelletDelivery
from autotrainer.device import DeviceConnection, DeviceThreadMessageKind

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


def run_monitor(port: str, timeout: int):
    device_connection = DeviceConnection(PelletDelivery(port), message_callback=message_queue_callback)

    device_connection.start()

    device_connection.send_message(DeviceThreadMessageKind.CONNECT)

    while True:
        if timeout > 0:
            # Run for the request time and exit.  Primarily supports automated testing by ensuring can launch and close
            # cleanly.
            time.sleep(timeout)
            device_connection.request_terminate()
            logger.debug("timeout reached, terminating")
            break
        else:
            cmd = input("Enter command: ")

            if cmd.startswith("q"):
                device_connection.request_terminate()
                break
            else:
                device_connection.send_message(PelletDeliveryMessageKind.RAW_COMMAND, cmd + "x")

    logger.info("waiting for device thread to terminate")

    device_connection.join()

    logger.info("done")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")
    parser.add_argument("-t", "--timeout", help="run for the specified number of seconds and exit",
                        type=int, default=0)

    args = parser.parse_args()

    run_monitor(args.port, args.timeout)
