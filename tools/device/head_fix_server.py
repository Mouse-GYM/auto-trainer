import argparse
import logging
import time
from random import random
from threading import Thread

import serial

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

weight = 0
switch_pin = 0
pressure_pin = 0


def get_value(input_val: str):
    if len(input_val) < 2:
        return None

    try:
        return int(input_val[1:])
    except:
        return None


def accept_commands():
    global weight, switch_pin, pressure_pin

    while True:
        cmd = input("")

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


def handle_command(s, cmd: str, msg: str):
    if cmd == "A":
        logger.info(f"servo: {int(msg)}")
    elif cmd == "L":
        pass
    elif cmd == "M":
        pass
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


def run_server(port: str, frequency: int, use_random: bool = False):
    global weight, switch_pin, pressure_pin

    logger.info(f"starting server on port {port} with update frequency {frequency}Hz")

    if use_random:
        logger.info("\tusing random data")
        mon_thread = None
        weight = 100
        switch_pin = 1
        pressure_pin = 512
    else:
        mon_thread = Thread(target=accept_commands)
        mon_thread.start()

    s = serial.Serial(port)

    ref_time = time.perf_counter_ns()

    interval_s = 1.0 / frequency
    interval_ns = interval_s * 1e9

    msg = ""

    while True:
        if time.perf_counter_ns() - ref_time >= interval_ns:
            ref_time = time.perf_counter_ns()
            s.write(f"s{weight}".encode())
            s.write(f"d{switch_pin}".encode())
            s.write(f"a{pressure_pin}n".encode())

            if use_random:
                next_val = random()
                weight += int((next_val - 0.5) * 10)
                if next_val < 0.05:
                    switch_pin = 0 if switch_pin == 1 else 1
                pressure_pin += int((next_val - 0.5) * 5)

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

    args = parser.parse_args()

    run_server(args.port, args.frequency, args.random)
