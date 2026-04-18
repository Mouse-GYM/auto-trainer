from typing import Protocol, Any, Optional


from autotrainer.core import MotorConfigurations, Offset3DTuple, Motor
from autotrainer.core.logging import get_verbose_logger
from autotrainer.device import MotorConfigurationFile, CompoundMovements, Device
from autotrainer.device.motor_steps import CompoundMovementDataSet

logger = get_verbose_logger(__name__)


class DeviceConnectionProtocol(Protocol):

    @property
    def device(self) -> Device:
        """Get the associated physical device"""
        raise NotImplementedError

    @property
    def read_limit(self) -> int:
        """Must return the read limit"""
        raise NotImplementedError

    @read_limit.setter
    def read_limit(self, value: int):
        raise NotImplementedError

    def request_connect(self):
        """Request the connection to the physical device to be established"""
        raise NotImplementedError

    def request_disconnect(self):
        """Request disconnection from the physical device"""
        raise NotImplementedError

    def join(self):
        """Join any of the thread/resources used during the connection"""

    def send_message(self, kind: int, data: Optional[Any] = None, context: Optional[Any] = None):
        """Send a message/command to the command writer handler thread"""

    def load_default_motor_config(self):
        default_motors_cfg_file = MotorConfigurationFile.DEFAULT_LOCATION.expanduser()
        if default_motors_cfg_file.exists():
            logger.notice("Reading and applying default motors config: %s", default_motors_cfg_file)
            motors_cfg = MotorConfigurationFile.from_file(default_motors_cfg_file)
            self.use_motor_configurations(motors_cfg)
        else:
            logger.warning(
                "Default motor config file %s not present, no motor config auto-applied, this might be critical",
                default_motors_cfg_file)

    def use_motor_configurations(self, data: MotorConfigurations):
        """Apply the given motor configuration"""
        raise NotImplementedError

    def load_default_move_config(self):
        default_move_cfg_file = CompoundMovements.DEFAULT_LOCATION.expanduser()
        if default_move_cfg_file.exists():
            logger.notice("Reading and applying default move config: %s", default_move_cfg_file)
            move_cfg = CompoundMovements.from_file(default_move_cfg_file)
            self.use_compound_movements(move_cfg)
        else:
            logger.warning(
                "Default move config file %s not present, no move config auto-applied, this might be critical",
                default_move_cfg_file)

    def use_compound_movements(self, data: CompoundMovementDataSet):
        """Apply the given motor compound movement"""
        raise NotImplementedError