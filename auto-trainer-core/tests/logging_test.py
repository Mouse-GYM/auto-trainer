from pathlib import Path

import subprocess
import sys


this_dir = Path(__file__).parent


def counts(sub, lines):
    return sum(1 for line in lines if sub in line)


def test_mp_file_handler(tmp_path):
    log_file = tmp_path.joinpath("foobar.log")
    cmd = [sys.executable, "-m", "exec_mp_log", log_file.as_posix()]
    data = subprocess.check_output(cmd, cwd=this_dir.joinpath("logging"))
    output = data.decode().splitlines()
    assert counts("prepending 1 records to", output) == 1
    assert counts("START", output) == 1
    assert counts("BEFORE", output) == 1
    assert counts("AFTER", output) == 1
    content = log_file.read_text().splitlines()
    assert counts("START", content) == 1
    assert counts("BEFORE", content) == 1
    assert counts("AFTER", content) == 1
    assert counts("CLOSE", content) == 100
