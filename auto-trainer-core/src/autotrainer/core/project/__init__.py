from multiprocessing.sharedctypes import Synchronized
from typing import Protocol, Optional

from .project_info import ProjectInfo
from .project_info import ProjectInterval


class ProjectDependentProtocol(Protocol):

    @property
    def project(self) -> ProjectInfo:
        """The associated current project-info"""

    @project.setter
    def project(self, value: ProjectInfo):
        """Project-info setter"""

    def set_main_watchdog_holder(self, value: Optional[Synchronized]):
        """Set the main watchdog value holder"""


ProjectDependentProtol = ProjectDependentProtocol  # previous typo alias
