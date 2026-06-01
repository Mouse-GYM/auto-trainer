
from dataclasses import dataclass


@dataclass
class AlarmDetectorConfig:
    use: bool = True  # decide if "used by/enabled with" the alarm monitor, or not
    is_emergency_condition: bool = False  # decide if trigger emergency_stop()/_resume(), or not.
        # only valid/used if use == True.
    allow_autoresume_on_cleared: bool = True  # decide if, when cleared, emergency_resume() is automatically called or not.
