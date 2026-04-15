"""
Temporary setup.py for auto-trainer top repo
"""

from pathlib import Path
from setuptools import setup

import tomli

this_dir = Path(__file__).parent.resolve()


auto_trainer_subprojects = this_dir.joinpath("auto_trainer_projects_order.txt").read_text().splitlines()


def is_sub_prj(r: str):
    return any(
        p in r
        for p in auto_trainer_subprojects
    )


def make_install_requires():
    requires = []
    all_projects = ["tools"] + auto_trainer_subprojects
    for sub_project in all_projects:
        p = this_dir.joinpath(sub_project, "pyproject.toml")
        with p.open("rb") as fh:
            content = tomli.load(fh)
            deps = content["project"]["dependencies"]
            requires.extend(deps)
            if not deps:
                print(f"{sub_project=} empty deps")
    requires = list(filter(lambda r: not is_sub_prj(r), requires))
    return requires


if __name__ == "__main__":
    install_requires = make_install_requires()
    # print(f"{install_requires=}")
    setup(
        # all others are filled via pyproject.toml
        install_requires=install_requires,
    )
