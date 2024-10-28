import os
import sys
from datetime import datetime

from autotrainer.core.project import ProjectInfo

base = "D:" if sys.platform == "win32" else "/home"
root = os.path.join(base, "auto-trainer", "output")
device_id = "A1357"


def test_today():
    when = datetime(2023, 6, 8)

    info = ProjectInfo(root=root, device_id=device_id, when=when)

    (location, today) = info.get_day_path()

    assert today == "20230608"

    assert location == os.path.join(root, "20230608", "A1357")


def test_hourly():
    when = datetime(2023, 6, 8, 8, 45, 23)

    info = ProjectInfo(root=root, device_id=device_id, when=when)

    hourly_source = info.get_interval_path("camera-1")

    assert hourly_source.location == os.path.join(root, "20230608", "A1357")

    assert hourly_source.prefix == f"20230608_A1357_h08_camera-1"

    assert hourly_source.interval == 8

def test_implicit_session():
    when = datetime(2024, 6, 8, 8, 45, 23)

    info = ProjectInfo(root=root, device_id=device_id, when=when)

    session_source = info.get_session_path("camera-1")

    assert session_source.location == os.path.join(root, "20240608", "A1357", "session001")

    assert session_source.prefix == f"20240608_A1357_session001_camera-1"

    assert session_source.session_index == 1

    # Would normally happen through calculate_next_session_index, but this uses the filesystem
    info.session.value = 9

    session_source = info.get_session_path("camera-1")

    assert session_source.location == os.path.join(root, "20240608", "A1357", "session009")

    assert session_source.prefix == f"20240608_A1357_session009_camera-1"

    assert session_source.session_index == 9

def test_explicit_session():
    when = datetime(2023, 6, 8, 8, 45, 23)

    info = ProjectInfo(root=root, device_id=device_id, when=when)

    session_source = info.get_session_path("camera-1", session=12)

    assert session_source.location == os.path.join(root, "20230608", "A1357", "session012")

    assert session_source.prefix == f"20230608_A1357_session012_camera-1"

    assert session_source.session_index == 12


if __name__ == '__main__':
    test_today()

    test_hourly()

    test_implicit_session();

    test_explicit_session()
