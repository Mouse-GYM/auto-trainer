import math
import typing


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

    def read(self, max_count: int = math.inf) -> typing.Any:
        """ Reads the available number of values from the interface up to max_count

        :param max_count: maximum number of values to read
        :returns typing.Any: the data
        :rtype: typing.Any
        """
        pass

    def write(self, value: typing.Any) -> int:
        """ Writes the content value(s) to the interface

        :param value: The content to be written
        :return: the number of values written"""
        pass

    def write_str(self, value: str) -> int:
        """ Writes the string to the interface

        :param value: The string to be written
        :return: the number of bytes written"""
        pass

