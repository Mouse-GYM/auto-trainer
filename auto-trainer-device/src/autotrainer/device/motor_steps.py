from typing import Protocol


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
        return self._steps.copy()

    @property
    def is_empty(self):
        return self._steps is not None and len(self._steps) == 0


class CompoundMovementDataSet(Protocol):

    @property
    def load_pellet(self) -> MotorSteps: ...

    @property
    def send_pellet(self) -> MotorSteps: ...

    @property
    def cover_pellet(self) -> MotorSteps: ...

    @property
    def release_pellet(self) -> MotorSteps: ...
