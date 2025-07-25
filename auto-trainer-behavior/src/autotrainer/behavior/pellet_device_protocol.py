from typing import Protocol, Optional
from uuid import UUID

from autotrainer.core import ObservableObjectProtocol, Offset3DTuple


class PelletDeviceProtocol(ObservableObjectProtocol, Protocol):
    """
    Defines an expected/required set of commands from the pellet device that are used as part of the behavior algorithm
    and state machine.
    """

    def set_x(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        """
        Change the X stepper location and set it as the X-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_y(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        """
        Change the Y stepper location and set it as the Y-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_z(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        """
        Change the Z stepper location and set it as the Z-axis pellet release location.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def move_x(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        """
        Move the X stepper.  This may not be supported on all device platforms.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def move_y(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        """
        Move the Y stepper.  This may not be supported on all device platforms.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def move_z(self, value: int, *, absolute: bool = True) -> Optional[UUID]:
        """
        Move the Z stepper.  This may not be supported on all device platforms.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def send_home(self) -> Optional[UUID]:        """
        Request a move to 0, 0, 0.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def load_pellet(self) -> Optional[UUID]:        """
        Request a full load cycle to scoop the pellet from the bin.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def send_pellet(self) -> Optional[UUID]:
        """
        Request a move from the current position to the "send" location stored in the hardware.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def cover_pellet(self) -> Optional[UUID]:
        """
        Request the barrier arm close and cover the pellet.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def release_pellet(self) -> Optional[UUID]:
        """
        Request the barrier arm open and expose the pellet.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def play_tone(self, frequency: int, duration: float) -> Optional[UUID]:
        """
        Request the device play a tone.

        :return: A token to expect from the device message handler when the request is complete.
        """

    def set_motor_drift(self, drift: Offset3DTuple):
        """Set the motor drift offset"""
