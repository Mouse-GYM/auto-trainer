"""
Utility functions to stepper the stepper motor
"""

"""
Return - Number of turns of the stepper motor from a linear distance. 
2.44 is from the linear travel spec of the motor
"""


def mm_to_turns(mm: float) -> float:
    return mm / 2.44


"""
Return - Number of mm in linear distance from number of turns of the stepper motor. 
2.44 is from the linear travel spec of the motor
"""


def turns_to_mm(turns: float) -> float:
    return turns * 2.44
