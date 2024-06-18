import numpy

from ..pose_model import PoseModel


class MemoryPoseModel(PoseModel):
    def __init__(self, shape: (int, int) = (300, 200), batchsize: int = 2):
        super().__init__()

        self._shape = shape
        self._batchsize = batchsize

    def is_valid(self) -> bool:
        return True

    def load(self):
        self.body_parts.append("body_part_1")
        self.body_parts.append("body_part_2")

    def predict(self, frames: numpy.ndarray) -> numpy.ndarray:
        pose = numpy.zeros((self._batchsize, len(self.body_parts) * 3))

        for idx in range(self._batchsize):
            data = numpy.random.rand(len(self.body_parts), 3)

            data[: 0] *= self._shape[0]
            data[: 1] *= self._shape[1]

            pose[idx, :] = data.flatten()

        return pose
