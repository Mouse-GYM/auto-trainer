# Installation

*Work in Progress* - there may be out of date or missing information.

## Requirements
Absent specific camera support, *Auto Trainer* is independent of platform and Python version >= 3.8.  Choice of cameras may 
place requirements on platform or Python version.

### System Installs/Requirements
#### Anaconda
Anaconda is required for full feature support.

Tested with `Anaconda3-2023.09-0-Linux-aarch64.sh`, `Anaconda3-2025.12-2-Linux-aarch64.sh`, and others.

### Teledyne/Blackfly Camera Support

* These cameras require installation of version 3 of the Spinnaker SDK/runtime for your platform.
* Platforms are limited to Windows and Ubuntu 20.04
* Python version is limited to 3.8
* See `install_spinnaker.sh` at https://github.com/Mouse-GYM/auto-trainer-device-deployment

```bash
gunzip spinnaker-3.2.0.62-arm64-pkg-20.04.tar.gz
tar -xvf spinnaker-3.2.0.62-arm64-pkg-20.04.tar
cd spinnaker-3.2.0.62-arm64/
sudo apt-get install libusb-1.0-0  # (no-op was already the most recent)
sudo apt-get --fix-broken install
sudo ./remove_spinnaker_arm.sh  # remove previous version if any
sudo ./install_spinnaker_arm.sh
```

**Nb:** this must be kept in sync with `https://github.com/Mouse-GYM/auto-trainer-device-deployment/tree/main/spinnaker`

## Platform Specific Requirements 

Please see https://github.com/Mouse-GYM/auto-trainer-device-deployment

## Package Installation

1) Create a Conda environment ; only once first time:
`conda create -n auto-trainer-1 python=3.8`

2) activate it: `conda activate auto-trainer-1` ; **every time**.
   Nb: This is now included with device-deployment too.

3) Once first time: clone this repository.
    - create or update the ~/.netrc file so that it contains :
    ```
    machine github.com
    login Mouse-Gym
    password <PASTE_THE_PAT_HERE>
    ```
    and replace `<PAST_THE_PAT_HERE>` by what you will be given for it.
    - then clone the current repository:
    `git clone https://github.com/Mouse-GYM/auto-trainer.git`, and enter it: `cd auto-trainer`

4) FLIR ; only once first time.
   To include support for Teledyne/Blackfly cameras, install the appropriate wheel for your platform, *e.g.,*
   - `pip install ./library/spinnaker_python-3.2.0.62-cp38-cp38-linux_aarch64.whl`
   - `pip install ./library/spinnaker_python-3.2.0.62-cp38-cp38-linux_x86_64.whl`
   - `pip install .\library\spinnaker_python-3.2.0.62-cp38-cp38-win_amd64.whl`

   **Nb:** this must also be kept in sync with `https://github.com/Mouse-GYM/auto-trainer-device-deployment/tree/main/spinnaker`

5) **Jetson Only** and only once first time:
   1) `conda install --channel=conda-forge ffmpeg=6.1.2 libgomp ncurses`
      --channel=conda-forge: Use that conda channel. Which is required here.
      libgomp and ncurses are also required to get more recent, and built with appropriate flags,
      versions than the native system corresponding libraries,
      which are not recent enough/have some incompatibilities with others libraries used by the application.
   2) Unfortunately the nvidia torch wheel version/tag is not fully valid (from a version spec/syntax pov),
      and prevent to be installed with regular index-url, so we have to :
      - `wget https://developer.download.nvidia.cn/compute/redist/jp/v512/pytorch/torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl`
      - `pip install ./torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl`
   3) On the other hand, the nvidia tensorflow wheel version is valid, so we can do:
      - `pip install tensorflow==2.12.0+nv23.06 --extra-index-url https://developer.download.nvidia.com/compute/redist/jp/v512`
   4) `pip install ./path/to/pyjerrycan-1.2.5-cp38-cp38-linux_aarch64.whl`
     - Usually pyjerrycan wheel file is copied in home dir.

6) Activate an appropriate branch, *e.g.,*
`git checkout develop`

   Neither script below switches branches: `update.sh` warns when the checkout is not `develop` and
   continues, and `auto-trainer.sh` reports a non-`develop` or modified checkout to the application as a
   custom build. Whatever is selected here is what both act on.

7) From the repository directory, install the project and its dependencies.
`./update.sh`

   This fetches `origin`, brings a `develop` checkout up to date, and performs the editable install.
   It is also the routine update command — run it again whenever the machine needs to be brought current,
   rather than repeating the install by hand.

8) From the repository directory, start the acquisition application.
`./auto-trainer.sh` is generally preferred over `python -m tools.acquisition.gui`. It supplies the build and version information the
   application uses to report whether the machine is running a custom or out-of-date build; started any
   other way, the application has nothing to report. Arguments are forwarded, *e.g.,*
   `./auto-trainer.sh --help`.


### Environment requirements
Please see https://github.com/Mouse-GYM/auto-trainer-device-deployment/ for full information,
more particularly its `home-install/.load_autotrainer_env.sh` file.

Using a conda env, we have to/should export LD_LIBRARY_PATH with the correct library directories from the conda env.
Also, there are some libraries that need to be preloaded (given some incompatibilities between them and other(s)),
using export LD_PRELOAD.

A block similar to the following must be used or added to `.bashrc`/`.bash_profile` :

```bash
# need be activated before below exports (before ${CONDA_PREFIX} usage):
conda activate auto-trainer-1

# ensure system libraries from conda env are used :
export LD_LIBRARY_PATH=${CONDA_PREFIX}/lib64:${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH}

export LD_PRELOAD="${LD_PRELOAD}:${CONDA_PREFIX}/lib/libgomp.so"
```
