import argparse
import logging
import time

import serial

logging.basicConfig(level=logging.INFO)
logging.getLogger('autotrainer').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

fw_version = "0.0.0"


def clamp(value, min_v, max_v):
    if min_v > max_v:
        raise ValueError("min value must be less than or equal to max value")
    if value > max_v:
        return max_v
    if value < min_v:
        return min_v

    return value


class DeviceState:
    def __init__(self, s, version: str):
        self.serial = s
        self.version = version
        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.mouse_x = 5
        self.mouse_y = 25
        self.mouse_z = 5
        self.delivery_style = 0
        self.delivery_state = 0
        self.allow_button_style_change = 1
        self.allow_button_delivery = 1

    def handle_command(self, cmd: str, msg: str):
        logger.info(f"commands: {cmd} [{msg}]")

        self.print(cmd)

        if len(msg) > 0:
            self.print(msg)

        self.print("!")

        if cmd == "A":
            self.writeln(self.current_x)
            self.writeln(self.current_y)
            self.writeln(self.current_z)
        elif cmd == "B":
            self.writeln(self.mouse_x)
            self.writeln(self.mouse_y)
            self.writeln(self.mouse_z)
        elif cmd == "C":
            self.writeln(0)
            self.writeln(1)
            self.writeln(0)
            self.println("   ")
        elif cmd == "D":
            try:
                self.allow_button_style_change = int(msg)
                logger.info(f"allow_button_style_change: {self.allow_button_style_change}")
            except Exception as e:
                logger.error(f"allow_button_style_change: {e}")
        elif cmd == "E":
            try:
                self.allow_button_delivery = int(msg)
                logger.info(f"allow_button_delivery: {self.allow_button_delivery}")
            except Exception as e:
                logger.error(f"allow_button_delivery: {e}")
        elif cmd == "F":
            self.print(f"P{self.version}")
        elif cmd == "H":
            self.send_home()
        elif cmd == "I":
            try:
                self.mouse_x = clamp(int(msg), 0, 10)
            except Exception as e:
                logger.error(f"mouse_x: {e}")
        elif cmd == "J":
            try:
                self.mouse_y = clamp(int(msg), 0, 10)
            except Exception as e:
                logger.error(f"mouse_y: {e}")
        elif cmd == "K":
            try:
                self.mouse_z = clamp(int(msg), 0, 10)
            except Exception as e:
                logger.error(f"mouse_z: {e}")
        elif cmd == "L":
            try:
                self.delivery_style = int(msg)
                logger.info(f"delivery_style: {self.delivery_style}")
            except Exception as e:
                logger.error(f"delivery_style: {e}")
        elif cmd == "M":
            if self.delivery_style == 1:
                self.delivery_state = 1
            self.deliver_pellet()
            self.play_tone(6000)
        elif cmd == "N":
            logger.info(f"play tone {int(msg)}")
        elif cmd == "O":
            self.println("2000")
        elif cmd == "P":
            self.send_home()
            time.sleep(3)
            self.send_home()
        elif cmd == "Q":
            time.sleep(0.25)
        elif cmd == "R":
            self.play_tone(5000)
            time.sleep(0.25)
            self.delivery_state = 0
        elif cmd == "S":
            pass
        elif cmd == "U":
            pass
        elif cmd == "V":
            pass
        elif cmd == "W":
            pass
        elif cmd == "X":
            pass
        elif cmd == "Y":
            pass
        elif cmd == "Z":
            pass
        else:
            logger.warning(f"unimplemented command: {cmd}")

        self.println("%")

    def print(self, value: str):
        self.serial.write(value.encode())

    def println(self, value: str):
        self.serial.write(f"{value}\n".encode())

    def writeln(self, value: int):
        self.serial.write(f"{value}\n".encode())

    def send_homing(self):
        raise NotImplementedError("send_homing not available with %s", self.__class__)

    def send_home(self):
        logger.info("sending home")

        self.current_x = 0
        self.current_y = 0
        self.current_z = 0

        time.sleep(1)

    def deliver_pellet(self):
        self.writeln(self.delivery_state)

        logger.info("deliver pellet")

        time.sleep(1)

        if self.delivery_state == 1:
            self.writeln(73)
        else:
            self.writeln(37)

    def play_tone(self, freq: int):
        logger.info("play tone")

        self.println(f"T{freq}")


def run_server(port: str, version: str):
    s = serial.Serial(port, baudrate=115200)

    cmd = ""
    msg = ""

    device = DeviceState(s, version)

    in_command: bool = False
    have_command: bool = False

    logger.info(f"pellet delivery server started on {port}")
    logger.info(f"pellet delivery firmware version {fw_version}")

    while True:
        if s.in_waiting > 0:
            if not in_command:
                cmd = s.read(1).decode()
                if cmd != "x":
                    in_command = True
                    print(cmd)

            while s.in_waiting > 0:
                data = s.read(1).decode()
                print("\t" + data)
                if data == "x":
                    have_command = True
                    break
                msg += data

            if have_command:
                device.handle_command(cmd, msg)
                in_command = False
                have_command = False
                cmd = ""
                msg = ""

        time.sleep(0.001)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("port", help="the serial port to use")
    parser.add_argument('-v', "--version", help="firmware version to report", default="2", type=str)

    args = parser.parse_args()

    fw_version = args.version

    run_server(args.port, args.version)
