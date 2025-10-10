import dataclasses


@dataclasses.dataclass
class PresenceDetectionConfig:
    pc_threshold: float = 2.2  # percent  -  lower makes more sensible to noise
    pc_high_exclude_threshold: float = 85  # percent ; this is to exclude too big % diff due to switch light ON/OFF.
    mask_lower_zero: int = 8 # gray value. this is "smooth" the difference, to be less sensible to noise. from 0 -> 255
    max_delay_skip_threshold: float = 0.5  # seconds, how much to keep/look at diff over previous frames
