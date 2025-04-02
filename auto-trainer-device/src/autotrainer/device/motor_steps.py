from typing import Protocol


class MotorSteps:
    @classmethod
    def from_dict(cls, name: str, data: dict):

        steps = []

        for step in data:
            if "type" in step and "value" in step:
                steps.append({step['type']: step['value']})

        return MotorSteps(name, steps)

    def __init__(self, name: str, steps: list):
        self._name = name
        self._steps = steps

    @property
    def steps(self):
        return self._steps.copy()


class CompoundMovementDataSet(Protocol):

    @property
    def load(self) -> MotorSteps: ...

    @property
    def send(self) -> MotorSteps: ...
