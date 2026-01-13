from typing import Protocol

from .project_info import ProjectInfo
from .project_info import ProjectInterval
from .project_info import video_write_ext


class ProjectDependentProtol(Protocol):

    @property
    def project(self) -> ProjectInfo:
        """The associated current project-info"""

    @project.setter
    def project(self, value: ProjectInfo):
        """Project-info setter"""
