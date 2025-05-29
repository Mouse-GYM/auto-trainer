import math

import pytest

from autotrainer.core.message.frame_index import FrameIndexCategory


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_frame_index_positive_or_null(idx):
    assert FrameIndexCategory(idx) is FrameIndexCategory.RECORDING_OR_OFFLINE_PROCESSING


@pytest.mark.parametrize("idx", [-1, -1.0, "-1"])
def test_frame_index_online_or_no_rec(idx):
    assert FrameIndexCategory(idx) is FrameIndexCategory.ONLINE_NO_RECORDING


@pytest.mark.parametrize("idx", [-2, -2.0, "-2"])
def test_frame_index_eof_record(idx):
    assert FrameIndexCategory(idx) is FrameIndexCategory.EOF_RECORDING


@pytest.mark.parametrize("idx", [-3, -3.0, "-3"])
def test_frame_index_specials(idx):
    assert FrameIndexCategory(idx) is FrameIndexCategory.EOF_OFFLINE_PROCESSING


@pytest.mark.parametrize("idx,xp_err", [
    (-20, ValueError),
    (-30, ValueError),
    (1.1, ValueError),
    ("foobar", ValueError),
    (math.inf, OverflowError),
])
def test_frame_unknown(idx, xp_err):
    with pytest.raises(xp_err) as err_ctx:
        FrameIndexCategory(idx)
