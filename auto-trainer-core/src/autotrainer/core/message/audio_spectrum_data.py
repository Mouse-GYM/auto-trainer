from dataclasses import dataclass
from typing import List

from autotrainer.core.message.audio_spectrum_message import AudioSpectrumMessage


@dataclass
class AudioSpectrumData(AudioSpectrumMessage):
    """
    Default class that implements the AudioSpectrumMessage protocol.  Actual hardware devices will likely deliver their
    own object that implements the protocol.  However, this class can be used to read back data from the output files
    for playback, reprocessing, or other tasks.
    """
    when_val: float
    index_val: int
    magnitudes_val: List[float]  # values are dB unit

    @property
    def when(self) -> float:
        return self.when_val

    @property
    def index(self) -> int:
        return self.index_val

    @property
    def magnitudes(self) -> List[float]:
        return self.magnitudes_val
