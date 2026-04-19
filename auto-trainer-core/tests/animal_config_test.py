import pytest

from autotrainer.core import AnimalSubject
from autotrainer.core.animal.animal_subject import AnimalPelletCounts


def test_save_load(tmp_path):
    animal = AnimalSubject(
        name="animal1",
        is_pellet_dcs=True,
        pellet_x=-1,
        pellet_y=1,
        pellet_z=2,
        target_y_limit=0.88,
        pellet_counts_day=AnimalPelletCounts(
            presented=10,
            reaches=5,
            success_reaches=3,
            consumed=4,
        ),
        pellet_counts_total=AnimalPelletCounts(
            presented=20,
            reaches=15,
            success_reaches=12,
            consumed=14,
        )
    )
    assert isinstance(animal.id, str) and len(animal.id) > 0
    dest = tmp_path.joinpath("animal.json")
    animal.to_file(dest)
    animal2 = AnimalSubject.from_file(dest)
    assert animal == animal2
    for k, v in animal.__dict__.items():
        setattr(animal, k, object())
        assert animal != animal2
        setattr(animal, k, v)
        assert animal == animal2
