import argparse
import logging
import os
import time
from queue import Queue

from autotrainer.core import MeasurementData, SystemStatusMessageKind, EventManager, SystemMessageHandler

logging.basicConfig(level=logging.INFO)
logging.getLogger("root").setLevel(logging.WARNING)
logging.getLogger("autotrainer").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# A work in progress to be able to reprocess data files to diagnose issues, replay events, etc.


def process_data(file: str, batch_size: int = 20):
    measurements = MeasurementData.from_file(file)

    print(len(measurements))

    queue = Queue()

    reader = SystemMessageHandler(queue)

    reader.start()

    measurement_buffer = []

    for measurement in measurements:
        measurement_buffer.append(measurement)

        if len(measurement_buffer) == batch_size:
            while not queue.empty():
                time.sleep(0.01)
            queue.put((SystemStatusMessageKind.MEASUREMENT, measurement_buffer))
            measurement_buffer = []

    reader.request_terminate()

    print("waiting for processing to complete")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("file", help="the measurements CSV data file")

    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error("The data file does not exist")

    EventManager.default()

    process_data(args.file)
