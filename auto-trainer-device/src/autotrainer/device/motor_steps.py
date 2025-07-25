from typing import Protocol
from copy import copy


class MotorSteps:
    @classmethod
    def from_dict(cls, name: str, data: dict):
        steps = []
        for step in data:
            if "type" in step and "value" in step:
                steps.append({step['type']: step['value']})

        return MotorSteps(name, steps)

    def __init__(self, name: str = None, steps: list = None):
        self._name = name
        self._steps = steps

    @property
    def steps(self):
        return copy(self._steps)

    @property
    def is_empty(self):
        return self._steps is None or len(self._steps) == 0


class CompoundMovementDataSet(Protocol):

    @property
    def load_pellet(self) -> MotorSteps: ...

    @property
    def send_pellet(self) -> MotorSteps: ...

    @property
    def cover_pellet(self) -> MotorSteps: ...

    @property
    def release_pellet(self) -> MotorSteps: ...

    @property
    def open_tunnel_gate(self) -> MotorSteps: ...

    @property
    def close_tunnel_gate(self) -> MotorSteps: ...
