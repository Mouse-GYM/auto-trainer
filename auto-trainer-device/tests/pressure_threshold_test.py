import csv
from pathlib import Path

from autotrainer.device.head_fix import HeadFixMeasurement
from autotrainer.device.head_fix_reader import ForceDetector


def test_threshold_behavior():
    path = Path(__file__).parent.joinpath("fixtures").joinpath("pressure_threshold_sample.csv")

    with open(str(path), mode="r") as file:
        csv_data = csv.reader(file)

        trigger_count = 0

        measurement_buffer = []

        detector = ForceDetector()

        for line in csv_data:
            if line[0] == "Time":
                continue

            measurement = HeadFixMeasurement(when=float(line[0]), timestamp=int(float(line[1])), weight=float(line[2]),
                                             switch=int(line[3]) == 1, pressure=int(line[4]),
                                             temperature=float(line[5]),
                                             humidity=float(line[6]))

            measurement_buffer.append(measurement.pressure)

            if len(measurement_buffer) == 20:
                result = detector.update(measurement_buffer)
                if result:
                    trigger_count += 1
                measurement_buffer.clear()

        assert trigger_count == 20


if __name__ == '__main__':
    test_threshold_behavior()
