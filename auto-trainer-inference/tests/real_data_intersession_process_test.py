import os
from datetime import datetime
from pathlib import Path

import verboselogs

from autotrainer.inference.analysis import intersession_process, IntersessionResponse


this_dir = Path(__file__).parent.resolve()


import pytest

@pytest.mark.skipif(os.name != "posix", reason="disabled on non-posix")
def test_fp_and_xp_not_same(project_info, caplog):

    project_info.session = 2
    project_info.root = this_dir.joinpath("fp-and-xp-not-same").as_posix()
    project_info.device_id = "agx001"
    project_info.when = datetime(2025, 6, 23)
    caplog.set_level(verboselogs.VERBOSE)
    res = intersession_process(
        project_info,
        calib_dir=this_dir.joinpath("4mm_6r_8c_4x"),
    )
    assert "Correcting expected_frame_count from " in caplog.text
    assert isinstance(res, IntersessionResponse)
    assert res.food_consumed == 0
    assert res.pellets_presented == 0
    assert res.successful_reaches == 0


@pytest.mark.skipif(os.name != "posix", reason="disabled on non-posix")
def test_index_error(project_info, caplog):
    # >           dropped_frame_vector[current_frame] = 0  # Mark current frame as successful
    # E           IndexError: index 378 is out of bounds for axis 0 with size 378
    project_info.session = 59
    project_info.root = this_dir.joinpath("index_error").as_posix()
    project_info.device_id = "agx001"
    project_info.when = datetime(2025, 8, 6)
    caplog.set_level(verboselogs.VERBOSE)
    with pytest.raises(IndexError, match="index 378 is out of bounds for axis 0"):
        intersession_process(
            project_info,
            calib_dir=this_dir.joinpath("4mm_6r_8c_4x"),
        )
    # TODO: fix underlying issue


def test_agx001_20251015_15(project_info, benchmark):
    project_info.root = this_dir.as_posix()
    project_info.session = 15
    project_info.device_id = "agx001"
    project_info.when = datetime(2025, 10, 15)
    res =  benchmark(lambda: intersession_process(
        project_info,
        calib_dir=this_dir.joinpath("4mm_6r_8c_4x"),
    ))
    print(res)
    assert res == IntersessionResponse(
        pellet_x=-1, pellet_y=1, pellet_z=0,
        food_consumed=0, successful_reaches=0, pellets_presented=1,
    )
