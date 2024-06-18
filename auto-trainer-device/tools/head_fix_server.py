import argparse
import logging
import time
from random import random
from threading import Thread

import serial

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

weight = 0
switch_pin = 0
pressure_pin = 0
temperature = 0
humidity = 0

fw_version = "0.0.0"


def get_value(input_val: str):
    if len(input_val) < 2:
        return None

    try:
        return int(input_val[1:])
    except:
        return None


def accept_user_commands():
    global weight, switch_pin, pressure_pin, temperature, humidity

    while True:
        cmd = input()

        if cmd.startswith("q"):
            break
        elif cmd.lower().startswith("s"):
            val = get_value(cmd)
            if val is not None:
                weight = val
        elif cmd.lower().startswith("d"):
            switch_pin = 0 if switch_pin == 1 else 1
        elif cmd.lower().startswith("a"):
            val = get_value(cmd)
            if val is not None:
                pressure_pin = val
        elif cmd.lower().startswith("t"):
            val = get_value(cmd)
            if val is not None:
                temperature = val
        elif cmd.lower().startswith("h"):
            val = get_value(cmd)
            if val is not None:
                humidity = val


def handle_command(s, cmd: str, msg: str):
    global fw_version

    s.write(cmd.encode())

    if cmd == "A":
        logger.info(f"servo: {int(msg)}")
    elif cmd == "F":
        s.write(f"0H{fw_version}\n".encode())
    elif cmd == "L":
        pass
    elif cmd == "M":
        logger.info("tare scale")
    elif cmd == "N":
        pass
    elif cmd == "O":
        logger.info("report")
        s.write("Servo home: ".encode())
        s.write("10\n".encode())
        s.write("Scale tare: ".encode())
        s.write("20\n".encode())
        s.write("Points per mg: ".encode())
        s.write("30\n".encode())
        time.sleep(1)
    else:
        logger.info(f"{cmd}: {msg}")


def run_server(port: str, frequency: int, use_random: bool):
    global weight, switch_pin, pressure_pin, temperature, humidity, fw_version

    logger.info(f"head fix server on port {port} with update frequency {frequency}Hz")
    logger.info(f"head fix firmware version {fw_version}")

    if use_random:
        logger.info("head fix using random data")
        weight = 150
        switch_pin = 1
        pressure_pin = 512
        temperature = 220
        humidity = 500

    mon_thread = Thread(target=accept_user_commands)
    mon_thread.start()

    s = serial.Serial(port, baudrate=115200)

    interval_s = 1.0 / frequency
    interval_ns = interval_s * 1e9

    msg = ""

    start_time = time.perf_counter_ns()

    samples_sent = 0

    report_interval = frequency * 10

    while True:
        while time.perf_counter_ns() - start_time >= interval_ns * samples_sent:
            time.perf_counter_ns()
            s.write(f"s{weight}".encode())
            s.write(f"d{switch_pin}".encode())
            s.write(f"a{pressure_pin}".encode())
            s.write(f"t{temperature}".encode())
            s.write(f"h{humidity}".encode())
            s.write("n".encode())
            samples_sent += 1

            if samples_sent % report_interval == 0:
                logger.debug(f"{((1.0e9 * samples_sent) / (time.perf_counter_ns() - start_time)):.1f}Hz")

            if use_random:
                next_val = random() - 0.5
                weight += round(next_val * 2)
                if weight > 300:
                    weight -= 5
                if weight < 0:
                    weight += 5
                next_val = random()
                if next_val < 0.01:
                    switch_pin = 0 if switch_pin == 1 else 1
                next_val = next_val - 0.5
                pressure_pin += round(next_val * 5)
                next_val = random() - 0.5
                temperature += round(next_val * 2)
                next_val = random() - 0.5
                humidity += round(next_val * 2)

        while s.in_waiting > 0:
            data = s.read(1).decode()
            msg += data
            if data == 'x':
                break

        if len(msg) and msg[-1] == "x":
            handle_command(s, msg[0], msg[1:-1])
            msg = ""

        if mon_thread is not None and not mon_thread.is_alive():
            break


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")
    parser.add_argument("-f", "--frequency", help="the frequency for updates (Hz)", default=10, type=int)
    parser.add_argument('-r', "--random", action="store_true", help="randomly modify data")
    parser.add_argument('-v', "--version", help="firmware version to report", default="2", type=str)

    args = parser.parse_args()

    fw_version = args.version

    run_server(args.port, args.frequency, args.random)
