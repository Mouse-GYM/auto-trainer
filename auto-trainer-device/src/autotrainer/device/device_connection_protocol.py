from typing import Protocol

from autotrainer.core import MotorConfigurations
from autotrainer.core.logging import get_verbose_logger
from autotrainer.device import MotorConfigurationFile, CompoundMovementFile
from autotrainer.device.motor_steps import CompoundMovementDataSet

logger = get_verbose_logger(__name__)


class DeviceConnectionProtocol(Protocol):
    @property
    def read_limit(self) -> int: ...

    @read_limit.setter
    def read_limit(self, value: int): ...

    def request_connect(self): ...

    def request_disconnect(self): ...

    def join(self): ...

    def send_message(self, kind: int, data: object = None, context: object = None): ...

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

    def load_default_move_config(self):
        default_move_cfg_file = CompoundMovementFile.DEFAULT_LOCATION.expanduser()
        if default_move_cfg_file.exists():
            logger.notice("Reading and applying default move config: %s", default_move_cfg_file)
            move_cfg = CompoundMovementFile.from_file(default_move_cfg_file)
            self.use_compound_movements(move_cfg)
        else:
            logger.warning(
                "Default move config file %s not present, no move config auto-applied, this might be critical",
                default_move_cfg_file)

    def use_compound_movements(self, data: CompoundMovementDataSet):
        """Apply the given motor compound movement"""
