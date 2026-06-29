# Installation

*Work in Progress* - there may be out of date or missing information.

## Requirements
Absent specific camera support, *Auto Trainer* is independent of platform and Python version >= 3.8.  Choice of cameras may 
place requirements on platform or Python version.

### System Installs/Requirements
#### Anaconda
Anaconda is required for full feature support.  Tested with `Anaconda3-2023.09-0-Linux-aarch64.sh`.

### Teledyne/Blackfly Camera Support

* These cameras require installation of version 3 of the Spinnaker SDK/runtime for your platform.
* Platforms are limited to Windows and Ubuntu 20.04
* Python version is limited to 3.8

See `install_spinnaker.sh` at https://github.com/Mouse-GYM/auto-trainer-device-deployment

## Platform Specific Requirements 

Please see https://github.com/Mouse-GYM/auto-trainer-device-deployment

## Package Installation

1) Create a Conda environment ; only once first time:
`conda create -n auto-trainer-1 python=3.8`

2) activate it: `conda activate auto-trainer-1` ; **every time**.

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

   **Nb:** this must be kept in sync with `https://github.com/Mouse-GYM/auto-trainer-device-deployment/tree/main/spinnaker`

5) **Jetson Only** and only once first time:
   1) `conda install --channel=conda-forge ffmpeg=6.0.0`
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

7) From the repository directory perform the following Python package installation steps.
`pip install -e .`


### Environment requirements
Please see https://github.com/Mouse-GYM/auto-trainer-device-deployment/,
more particularly its `home-install/.load_autotrainer_env.sh` file.
