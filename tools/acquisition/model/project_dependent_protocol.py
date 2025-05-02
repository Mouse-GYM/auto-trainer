from typing import Protocol

from autotrainer.core import ProjectInfo


class ProjectDependentProtol(Protocol):
    @property
    def project(self) -> ProjectInfo:
        pass

    @project.setter
    def project(self, value: ProjectInfo) -> None: ...
