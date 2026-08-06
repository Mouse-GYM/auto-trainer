import os
import sys
import types
from typing import Any
from unittest import mock
from urllib.parse import ParseResult

import pytest

from autotrainer.video import VideoManager


@pytest.fixture(autouse=True)
def mock_spinnaker(monkeypatch):
    """
    The spinnaker class import PySpin, for typehint, and only need "Camera" from it
    """
    mod_name = "PySpin"
    mod = types.ModuleType(mod_name)
    mod.Camera = None
    monkeypatch.setitem(sys.modules, mod_name, mod)


@pytest.mark.parametrize("url,xp_params,xp_parsed", [
    ("random://0", {},
ParseResult(scheme='random', netloc='0', path='', params='', query='', fragment='')),

    ("playback:///tmp/a.mp4", {},
     ParseResult(scheme='playback', netloc='', path='/tmp/a.mp4', params='', query='', fragment='')),

    ("random://0?width=150&height=300&", {'height': 300, 'width': 150},
     ParseResult(scheme='random', netloc='0', path='', params='', query='width=150&height=300&', fragment='')),

    ("opencv://0", {},
     ParseResult(scheme='opencv', netloc='0', path='', params='', query='', fragment='')),

    # spinnaker has different defaults than the others:
    ("spinnaker://12345678?exposure=145",
     {'exposure': 145},
     ParseResult(scheme='spinnaker', netloc='12345678', path='', params='', query='exposure=145', fragment='')),
])
def test_parse_url(url, xp_params, xp_parsed):
    parsed, params = VideoManager.parse_params(url)
    assert parsed == xp_parsed
    assert params == xp_params
