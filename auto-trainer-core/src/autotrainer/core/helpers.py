import inspect
from typing import Callable


def has_kwarg(func: Callable, kwarg_name: str) -> bool:
    # Get the function's signature
    sig = inspect.signature(func)

    # 1. Check if the specific keyword argument name exists
    if kwarg_name in sig.parameters:
        param = sig.parameters[kwarg_name]
        # Ensure it's not a positional-only argument
        return param.kind != inspect.Parameter.POSITIONAL_ONLY

    # 2. Check if the function accepts arbitrary keyword arguments (**kwargs)
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
