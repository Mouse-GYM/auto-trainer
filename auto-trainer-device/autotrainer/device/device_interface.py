import math


class DeviceInterface:
    """ Defines the required methods for a class that provides low-level communication with a device, such as serial"""

    def open(self) -> bool:
        """ Opens the interface

        This method should not raise an exception and return False instead.  Exception details may be logged.

        :return: True if successfully opened
        """
        return False

    def close(self):
        pass

    @property
    def is_open(self) -> bool:
        return False

    def can_read(self) -> bool:
        pass

    def read(self, max_count: int = math.inf) -> bytes:
        """ Reads the available number of bytes from the interface up to max_count

        :param max_count: maximum number of bytes to read
        :returns bytes: the byte array of data
        :rtype: bytes
        """
        pass

    def write(self, value: bytes) -> int:
        """ Writes the byte array to the interface

        :param value: The byte array to be written
        :return: the number of bytes written"""
        pass

    def write_str(self, value: str) -> int:
        """ Writes the string to the interface

        :param value: The string to be written
        :return: the number of bytes written"""
        pass
