from pathlib import Path
from typing import Protocol, Any, Optional, Set


from autotrainer.core import MotorConfigurations, Offset3DTuple, Motor
from autotrainer.core.logging import get_verbose_logger
from autotrainer.device import MotorConfigurationFile, CompoundMovements, Device
from autotrainer.device.motor_steps import CompoundMovementDataSet

logger = get_verbose_logger(__name__)


class DeviceConnectionProtocol(Protocol):

    @property
    def connected(self) -> bool:
        """Whether fully connected to device or not"""

    @property
    def watchdog_perf_c(self) -> float:
        """The alive/watchdog perf-counter of the related device"""
        return min(self.watchdog_reader_perf_c, self.watchdog_writer_perf_c)

    @property
    def watchdog_reader_perf_c(self) -> float:
        """The last alive/watchdog perf-counter of the related device reader thread"""

    @property
    def watchdog_writer_perf_c(self) -> float:
        """The last alive/watchdog perf-counter of the related device writer thread"""

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

    def await_acknowledge(self, tokens: Set, *, timeout: float=1, raise_on_timeout=True,
                          raise_on_command_error: bool = True, is_cancelled=lambda: False):
        """Await a set of tokens to be acknowledged"""

    @staticmethod
    def load_default_motor_config(config_path: Optional[Path] = None) -> MotorConfigurations:
        if config_path is None:
            config_path = MotorConfigurationFile.DEFAULT_LOCATION.expanduser()
        if config_path.exists():
            logger.notice("Reading and applying default motors config: %s", config_path)
            motors_cfg = MotorConfigurationFile.from_file(config_path)
        else:
            logger.warning(
                "Default motor config file %s not present, empty motor config auto-applied, this might be critical",
                config_path)
            motors_cfg = MotorConfigurationFile()
        return motors_cfg

    @staticmethod
    def load_default_move_config(config_path: Optional[Path] = None) -> CompoundMovements:
        if config_path is None:
            config_path = CompoundMovements.DEFAULT_LOCATION.expanduser()
        if config_path.exists():
            logger.notice("Reading and applying default move config: %s", config_path)
            move_cfg = CompoundMovements.from_file(config_path)
        else:
            move_cfg = CompoundMovements()
            logger.warning(
                "Default move config file %s not present, builtin default move will be used",
                config_path)
        return move_cfg

    def use_motor_configurations(self, data: Optional[MotorConfigurations] = None, *, is_cancelled=lambda: False):
        """Apply the given motor configuration"""
        raise NotImplementedError

    def use_compound_movements(self, data: Optional[CompoundMovementDataSet] = None, *, is_cancelled=lambda: False):
        """Apply the given motor compound movement"""
        raise NotImplementedError
