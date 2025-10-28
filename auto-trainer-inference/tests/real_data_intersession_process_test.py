import dataclasses
import functools
import os
from datetime import datetime
from pathlib import Path
from typing import List

import h5py.h5f
import numpy
import verboselogs

from autotrainer.core import Offset3DTuple
from autotrainer.inference import PoseResponse, PoseLocation
from autotrainer.inference.analysis import intersession_process, IntersessionResponse

import pytest


this_dir = Path(__file__).parent.resolve()


def deep_almost_equal(obj1, obj2, places=3, delta=None):
    if dataclasses.is_dataclass(obj1):
        obj1 = dataclasses.asdict(obj1)
    if dataclasses.is_dataclass(obj2):
        obj2 = dataclasses.asdict(obj2)
    if isinstance(obj1, float) or isinstance(obj2, float):
        if delta is not None:
            assert abs(obj1 - obj2) <= delta
            return True
        else:
            assert round(abs(obj1 - obj2), places) == 0
            return True
    elif isinstance(obj1, dict) and isinstance(obj2, dict):
        assert set(obj1) == set(obj2)
        for key in obj1:
            if not deep_almost_equal(obj1[key], obj2[key], places, delta):
                return False
        return True
    elif isinstance(obj1, (tuple, list)) and isinstance(obj2, (tuple, list)):
        assert len(obj1) == len(obj2)
        if len(obj1) != len(obj2):
            return False
        for item1, item2 in zip(obj1, obj2):
            if not deep_almost_equal(item1, item2, places, delta):
                return False
        return True
    else:
        assert obj1 == obj2
        return True


def assert_pose_response_almost_equal(
    r1: PoseResponse, r2: PoseResponse,
    *, loc_delta=6, loc3d_delta=1.5, off_delta=1.5
):
    assert r1.sequence == r2.sequence
    assert r1.parts_flags == r2.parts_flags
    deep_almost_equal(r1.locations, r2.locations, delta=loc_delta)
    deep_almost_equal(r1.locations_3d, r2.locations_3d, delta=loc3d_delta)
    deep_almost_equal(r1.parts_3d_offsets, r2.parts_3d_offsets, delta=off_delta)


@pytest.fixture
def agx001_20251015_15(project_info):
    project_info.root = this_dir.as_posix()
    project_info.session = 15
    project_info.device_id = "agx001"
    project_info.when = datetime(2025, 10, 15)
    return project_info


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


@pytest.mark.bench
def test_intersession_process_bench_agx001_20251015_15(agx001_20251015_15, benchmark):
    res =  benchmark(lambda: intersession_process(
        agx001_20251015_15,
        calib_dir=this_dir.joinpath("4mm_6r_8c_4x"),
    ))
    assert res == IntersessionResponse(
        pellet_x=-1, pellet_y=1, pellet_z=0,
        food_consumed=0, successful_reaches=0, pellets_presented=1,
    )


@pytest.mark.parametrize("frames_per_batch_per_cam,select_frames_method", [
    (1, "last_one"),
    pytest.param(2, "all_most_likely", marks=pytest.mark.xfail),
    # for some reason with 2 frames per batch (per cam), we have missing L_Hand in locations
    #
    #         elif isinstance(obj1, dict) and isinstance(obj2, dict):
    # >           assert set(obj1) == set(obj2)
    # E           AssertionError: assert {'Diamond', 'LH_flat', 'Triangle', 'Mouth', 'Pellet', 'Star', 'Nose'} \
    #               == {'L_Hand', 'Diamond', 'LH_flat', 'Mouth', 'Star', 'Triangle', 'Nose', 'Pellet'}
    # E             Full diff:
    # E               {
    # E                   'Diamond',
    # E                   'LH_flat',
    # E             -     'L_Hand',
    # E                   'Mouth',
    # E                   'Nose',
    # E                   'Pellet',
    # E                   'Star',
    # E                   'Triangle',
    # E               }

    (3, "last_one"),
    (3, "all_most_likely"),
    (5, "last_one"),
    (5, "all_most_likely"),
    (10, "all_most_likely"),
])
def test_pose_algo_process_frames_agx001_20251015_15(pose_algo, agx001_20251015_15, frames_per_batch_per_cam, select_frames_method):
    parts = ['Pellet', 'RH_flat', 'RH_spread', 'RH_grab', 'LH_flat', 'LH_spread', 'LH_grab',
             'Star', 'Tongue_mid', 'Tongue_tip', 'Nose', 'Triangle', 'Mouth', 'Diamond']
    pairs_3d = [
        ('Diamond', 'Triangle'),
    ]
    pose_algo.process_frames_select_frames_method = select_frames_method
    pose_algo.initialize(parts)
    sp = agx001_20251015_15.get_session_path()
    fhs = []
    tables = []
    for cam in ("left", "right"):
        p = Path(sp.location).joinpath(f"{sp.prefix}_{cam}_raw2D.h5")
        fh = h5py.File(p, "r")
        fhs.append(fh)
        tables.append(fh["df_with_missing"]["table"])
    #
    cur_frame_idx = 0
    #
    frames_per_batch = frames_per_batch_per_cam
    all_frames = [[] for _ in range(len(fhs))]
    for table, frames in zip(tables, all_frames):
        for idx in range(cur_frame_idx, cur_frame_idx + frames_per_batch):
            f = table[idx][1]
            assert isinstance(f, numpy.ndarray)
            frames.append(f.reshape((len(parts), -1)))
    cur_frame_idx += frames_per_batch

    res = pose_algo.process_frames(*all_frames, pairs_3d_offsets=pairs_3d)
    assert isinstance(res, PoseResponse)

    # when using last frame of batch:
    expected = PoseResponse(
        sequence=1,
        parts_flags=(
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True},
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': True, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True},
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True}), locations=[
        {'Pellet': PoseLocation(name='Pellet', index=0, x=107.18849468231201, y=124.11833190917969),
         'Star': PoseLocation(name='Star', index=7, x=157.89800357818604, y=98.02168691158295),
         'Nose': PoseLocation(name='Nose', index=10, x=81.19415855407715, y=89.2825698852539),
         'Triangle': PoseLocation(name='Triangle', index=11, x=100.96263575553894, y=154.61319971084595),
         'Mouth': PoseLocation(name='Mouth', index=12, x=61.63555586338043, y=103.7043285369873),
         'Diamond': PoseLocation(name='Diamond', index=13, x=30.862200021743774, y=71.6781370639801)},
        {'Pellet': PoseLocation(name='Pellet', index=0, x=84.202712059021, y=127.75618600845337),
         'LH_flat': PoseLocation(name='LH_flat', index=4, x=142.5007290840149, y=57.30223035812378),
         'Star': PoseLocation(name='Star', index=7, x=136.81033945083618, y=121.13375759124756),
         'Nose': PoseLocation(name='Nose', index=10, x=104.89548110961914, y=74.90717458724976),
         'Triangle': PoseLocation(name='Triangle', index=11, x=65.31067943572998, y=152.19582509994507),
         'Mouth': PoseLocation(name='Mouth', index=12, x=106.30647206306458, y=91.57262086868286),
         'Diamond': PoseLocation(name='Diamond', index=13, x=37.36961615085602, y=66.14892673492432),
         'L_Hand': PoseLocation(name='L_Hand', index=-1, x=142.5007290840149, y=57.30223035812378)}],
        parts_3d_offsets={
        'Diamond': {'Triangle': Offset3DTuple(3.7954362324560265, -10.707559950520782, -12.157127561207961)}},
        locations_3d={'Diamond': Offset3DTuple(-66.66986318624589, -68.63968712410409, 18.349303122667),
                      'Triangle': Offset3DTuple(-70.46529941870192, -57.932127173583304, 30.50643068387496)})

    # for when using most likelihood result:
    expected = PoseResponse(
        sequence=1,

        parts_flags=(
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True},
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': True, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True},
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True}),

        locations=[
        {'Pellet': PoseLocation(name='Pellet', index=0, x=107.18849468231201, y=124.11833190917969),
         'Star': PoseLocation(name='Star', index=7, x=157.89800357818604, y=98.02168691158295),
         'Nose': PoseLocation(name='Nose', index=10, x=81.19415855407715, y=89.2825698852539),
         'Triangle': PoseLocation(name='Triangle', index=11, x=100.96263575553894, y=154.61319971084595),
         'Mouth': PoseLocation(name='Mouth', index=12, x=61.63555586338043, y=103.7043285369873),
         'Diamond': PoseLocation(name='Diamond', index=13, x=30.862200021743774, y=71.6781370639801)},
        {'Pellet': PoseLocation(name='Pellet', index=0, x=84.202712059021, y=127.75618600845337),
         'LH_flat': PoseLocation(name='LH_flat', index=4, x=142.5007290840149, y=57.30223035812378),
         'Star': PoseLocation(name='Star', index=7, x=136.81033945083618, y=121.13375759124756),
         'Nose': PoseLocation(name='Nose', index=10, x=104.89548110961914, y=74.90717458724976),
         'Triangle': PoseLocation(name='Triangle', index=11, x=65.31067943572998, y=152.19582509994507),
         'Mouth': PoseLocation(name='Mouth', index=12, x=106.30647206306458, y=91.57262086868286),
         'Diamond': PoseLocation(name='Diamond', index=13, x=37.36961615085602, y=66.14892673492432),
         'L_Hand': PoseLocation(name='L_Hand', index=-1, x=142.5007290840149, y=57.30223035812378)}],

        parts_3d_offsets={
        'Diamond': {'Triangle': Offset3DTuple(3.7954362324560265, -10.707559950520782, -12.157127561207961)}},

        locations_3d={'Diamond': Offset3DTuple(-66.66986318624589, -68.63968712410409, 18.349303122667),
                      'Triangle': Offset3DTuple(-70.46529941870192, -57.932127173583304, 30.50643068387496)})

    assert_pose_response_almost_equal(res, expected)

    # also shows that we can also process_frames with different frames_per_batch:
    frames_per_batch = 15
    all_frames = [[] for _ in range(len(fhs))]
    for table, frames in zip(tables, all_frames):
        for idx in range(cur_frame_idx, cur_frame_idx + frames_per_batch):
            f = table[idx][1]
            assert isinstance(f, numpy.ndarray)
            frames.append(f.reshape((len(parts), -1)))
    cur_frame_idx += frames_per_batch

    res = pose_algo.process_frames(*all_frames, pairs_3d_offsets=pairs_3d)
    assert isinstance(res, PoseResponse)

    # when using last frame of batch:
    expected = PoseResponse(
        sequence=2,
        parts_flags=(
            {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False,
             'LH_spread': False,
             'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
             'Mouth': True, 'Diamond': True},
            {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': True,
             'LH_spread': False,
             'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
             'Mouth': True, 'Diamond': True},
            {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False,
             'LH_spread': False,
             'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
             'Mouth': True, 'Diamond': True}),
        locations=[
            {'Pellet': PoseLocation(name='Pellet', index=0, x=107.04211616516113, y=123.86626148223877),
             'Star': PoseLocation(name='Star', index=7, x=158.24821877479553, y=97.93739342689514),
             'Nose': PoseLocation(name='Nose', index=10, x=84.43089017271996, y=81.8777265548706),
             'Triangle': PoseLocation(name='Triangle', index=11, x=101.0415391921997, y=154.65687561035156),
             'Mouth': PoseLocation(name='Mouth', index=12, x=64.20773363113403, y=100.37636175751686),
             'Diamond': PoseLocation(name='Diamond', index=13, x=30.646739721298218, y=71.81137537956238)},
            {'Pellet': PoseLocation(name='Pellet', index=0, x=84.36599445343018, y=127.89733743667603),
             'LH_flat': PoseLocation(name='LH_flat', index=4, x=146.16585052013397, y=63.08906579017639),
             'Star': PoseLocation(name='Star', index=7, x=137.04680728912354, y=121.26210641860962),
             'Nose': PoseLocation(name='Nose', index=10, x=104.87004232406616, y=72.21701335906982),
             'Triangle': PoseLocation(name='Triangle', index=11, x=65.36092472076416, y=152.2200870513916),
             'Mouth': PoseLocation(name='Mouth', index=12, x=106.08131313323975, y=90.71567392349243),
             'Diamond': PoseLocation(name='Diamond', index=13, x=37.1789847612381, y=66.1664891242981),
             'L_Hand': PoseLocation(name='L_Hand', index=-1, x=146.16585052013397, y=63.08906579017639)}],
        parts_3d_offsets={
            'Diamond': {'Triangle': Offset3DTuple(3.83952869291916, -10.731509655633126, -12.149132034044559)}},
        locations_3d={'Diamond': Offset3DTuple(-66.63453009108049, -68.65683688033108, 18.362526564485098),
                      'Triangle': Offset3DTuple(-70.47405878399965, -57.92532722469796, 30.511658598529657)})

    # for when using most likelihood result:
    expected2 = PoseResponse(
        sequence=2,
        parts_flags=(
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True},
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': True, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True},
        {'Pellet': True, 'RH_flat': False, 'RH_spread': False, 'RH_grab': False, 'LH_flat': False, 'LH_spread': False,
         'LH_grab': False, 'Star': True, 'Tongue_mid': False, 'Tongue_tip': False, 'Nose': True, 'Triangle': True,
         'Mouth': True, 'Diamond': True}),
       locations=[
        {'Pellet': PoseLocation(name='Pellet', index=0, x=107.04211616516113, y=123.86626148223877),
         'Star': PoseLocation(name='Star', index=7, x=158.24821877479553, y=97.93739342689514),
         'Nose': PoseLocation(name='Nose', index=10, x=84.43089017271996, y=81.8777265548706),
         'Triangle': PoseLocation(name='Triangle', index=11, x=101.0415391921997, y=154.65687561035156),
         'Mouth': PoseLocation(name='Mouth', index=12, x=64.20773363113403, y=100.37636175751686),
         'Diamond': PoseLocation(name='Diamond', index=13, x=30.646739721298218, y=71.81137537956238)},
        {'Pellet': PoseLocation(name='Pellet', index=0, x=84.36599445343018, y=127.89733743667603),
         'LH_flat': PoseLocation(name='LH_flat', index=4, x=146.16585052013397, y=63.08906579017639),
         'Star': PoseLocation(name='Star', index=7, x=137.04680728912354, y=121.26210641860962),
         'Nose': PoseLocation(name='Nose', index=10, x=104.87004232406616, y=72.21701335906982),
         'Triangle': PoseLocation(name='Triangle', index=11, x=65.36092472076416, y=152.2200870513916),
         'Mouth': PoseLocation(name='Mouth', index=12, x=106.08131313323975, y=90.71567392349243),
         'Diamond': PoseLocation(name='Diamond', index=13, x=37.1789847612381, y=66.1664891242981),
         'L_Hand': PoseLocation(name='L_Hand', index=-1, x=147.37112921476364, y=65.93348550796509)}],
        parts_3d_offsets={'Diamond': {
                          'Triangle': Offset3DTuple(3.83952869291916, -10.731509655633126, -12.149132034044559)}},
        locations_3d={'Diamond': Offset3DTuple(-66.63453009108049, -68.65683688033108, 18.362526564485098),
                      'Triangle': Offset3DTuple(-70.47405878399965, -57.92532722469796, 30.511658598529657)})

    assert_pose_response_almost_equal(res, expected)


@pytest.mark.bench
def test_pose_algo_process_frames_bench_agx001_20251015_15(pose_algo, agx001_20251015_15, benchmark):
    def proc():
        parts = ['Pellet', 'RH_flat', 'RH_spread', 'RH_grab', 'LH_flat', 'LH_spread', 'LH_grab',
                 'Star', 'Tongue_mid', 'Tongue_tip', 'Nose', 'Triangle', 'Mouth', 'Diamond']
        pairs_3d = [
            ('Diamond', 'Triangle'),
        ]
        sp = agx001_20251015_15.get_session_path()
        fhs = []
        tables = []
        for cam in ("left", "right"):
            p = Path(sp.location).joinpath(f"{sp.prefix}_{cam}_raw2D.h5")
            fh = h5py.File(p, "r")
            fhs.append(fh)
            tables.append(fh["df_with_missing"]["table"])
        cur_frame_idx = 0
        frames_per_batch = 3
        while True:
            all_frames = [[] for _ in range(len(fhs))]
            for table, frames in zip(tables, all_frames):
                for idx in range(cur_frame_idx, cur_frame_idx + frames_per_batch):
                    if idx > len(table) - 1:
                        break
                    f = table[idx][1]
                    assert isinstance(f, numpy.ndarray)
                    frames.append(f.reshape((len(parts), -1)))
            if any(len(frames) < frames_per_batch for frames in all_frames):
                break
            cur_frame_idx += frames_per_batch
            pose_algo.process_frames(*all_frames, pairs_3d_offsets=pairs_3d)
        return cur_frame_idx

    res = benchmark(proc)
    assert res == 762
