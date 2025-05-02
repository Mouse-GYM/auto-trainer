from typing import Protocol, Optional
from uuid import UUID

from autotrainer.core import ObservableObjectProtocol


class TunnelDeviceProtocol(ObservableObjectProtocol, Protocol):
    """
    Defines an expected/required set of commands from the tunnel device that are used as part of the behavior algorithm
    and state machine.
    """

    def update_head_magnet_intensity(self, position: float) -> Optional[UUID]: ...
    """
    Request an update to the head magnet position.
    
    :param position: The % position [0, 100] to set the head magnet.
    
    :return: A token to expect from the device message handler when the request is complete.
    """

    def tare_load_cell(self) -> Optional[UUID]: ...
    """
    Request the load cell perform a tare operation.
    
    :return: A token to expect from the device message handler when the request is complete.
    """
