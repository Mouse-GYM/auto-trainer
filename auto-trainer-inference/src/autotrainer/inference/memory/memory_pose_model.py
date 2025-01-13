import typing

import numpy

from ..pose_model import PoseModel


class MemoryPoseModel(PoseModel):
    def __init__(self, batchsize: int = 2):
        super().__init__()

        self._batchsize = batchsize

        self.use_random = False

    def is_valid(self) -> bool:
        return True

    def load(self):
        self.body_parts.append("Pellet")
        self.body_parts.append("RH_flat")
        self.body_parts.append("RH_spread")
        self.body_parts.append("RH_grab")
        self.body_parts.append("LH_flat")
        self.body_parts.append("LH_spread")
        self.body_parts.append("LH_grab")
        self.body_parts.append("Star")
        self.body_parts.append("Tongue")
        self.body_parts.append("Nose")

    def predict(self, frames: numpy.ndarray) -> typing.List[numpy.ndarray]:
        all_frames = list()

        for idx in range(self._batchsize):
            if self.use_random:
                data = numpy.random.rand(len(self.body_parts), 3)
            else:
                data = numpy.zeros((len(self.body_parts), 3))

            # pose_predict normalizes on the assumption these values are in absolute frame size
            data[:, 0] *= frames.shape[2]
            data[:, 1] *= frames.shape[1]

            all_frames.append(data)

        return all_frames
