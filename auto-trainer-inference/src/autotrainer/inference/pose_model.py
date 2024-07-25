import typing

import numpy


class PoseModel:
    def __init__(self):
        self._body_parts = list()
        self._body_part_categories = list()
        self._body_parts_by_category = dict()

    @property
    def body_parts(self):
        return self._body_parts

    @property
    def body_part_categories(self):
        return self._body_part_categories

    def is_valid(self) -> bool:
        pass

    def load(self):
        pass

    def predict(self, frames: numpy.ndarray) -> typing.List[numpy.ndarray]:
        return numpy.empty((0, 3), dtype="float")
