from typing import Protocol, List, Dict, Any
from copy import copy


_missing = object()  # sentinel

class MotorSteps:

    @classmethod
    def from_raw(cls, name: str, data: List[Dict[str, Any]]):
        steps = []
        for step in data:
            step_type = step.get('type', _missing)
            step_value = step.get('value', _missing)
            if _missing in (step_type, step_value):
                raise ValueError(f"Missing 'type' or 'value' key for motor steps, got {step!r}")
            steps.append({step_type: step_value})
        return MotorSteps(name, steps)

    def __init__(self, name: str = "NA", steps: List[Dict[str, Any]] = None):
        self._name = name
        self._steps = steps

    def __repr__(self):
        return f"MotorSteps(name={self._name!r}, steps={self._steps})"

    @property
    def name(self) -> str:
        return self._name

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

    # NB: open|close_tunnel_gate unused:
    @property
    def open_tunnel_gate(self) -> MotorSteps: ...

    @property
    def close_tunnel_gate(self) -> MotorSteps: ...
