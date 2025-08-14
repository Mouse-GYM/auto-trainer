
# Protocol first (less strict)
from .inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration
from .pellet_device_protocol import PelletDeviceProtocol

from .intersession import IntersessionState
from .intersession.intersession_machine import IntersessionMachine
from .pellet import PelletMachine, PelletState
from .behavior_algorithm import BehaviorAlgorithm
from .behavior_event_kind import BehaviorEventKind

from .analysis import intersession_inference, intersession_process
from .system_machine import SystemMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol
