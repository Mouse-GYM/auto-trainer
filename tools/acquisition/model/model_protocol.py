from typing import Protocol

from autotrainer.core import ProjectInfo


class ModelProtocol(Protocol):

    @property
    def project(self) -> ProjectInfo:
        pass

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        pass

    def load_configuration(self, configuration: dict):
        pass

    def save_configuration(self) -> dict:
        pass
