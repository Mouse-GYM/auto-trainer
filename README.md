# Auto Trainer

*Work in Progress* - there may be out of date or missing information.

## Requirements
Absent specific camera support, *Auto Trainer* is independent of platform and Python version.  Choice of cameras may 
place requirements on platform or Python version. 

### Teledyne/Blackfly Camera Support

* These cameras require installation of version 3 of the Spinnaker SDK/runtime for your platform.
* Platforms are limited to Windows and Ubuntu 20.04
* Python version is limited to 3.8

## Installation
Create a default installation without specific camera support:

`pip install -r requirements.txt`

To include support for Teledyne/Blackfly cameras, install the appropriate wheel for your platform, *e.g.,* 

`pip install .\library\spinnaker_python-3.2.0.57-cp38-cp38-linux_aarch64.whl`

Wheels for supported platforms are included in `library/`.

To enable video recording

`conda install --channel=conda-forge ffmpeg=6.0.0`

### Platform Specific Installation 

#### Jetson

* Add user to dialout group to access UART.  Requires reboot.

## Getting Started

The root path of the project must be added to your python path for most tools and scripts.  If using an IDE, this may be handled
for you automatically, otherwise
* Bash/Zsh: `export PYTHONPATH=$PYTHONPATH:$PWD`
* Windows CMD: `set PYTHONPATH=%PYTHONPATH%;%CD%`
* Windows PowerShell: `$env:PYTHONPATH += Get-Location`


## Scripts

Most of the content in `scripts` are generally lightweight utilities to determine if various components of the system are working as expected.

* acquire_images
* capture_camera
* head_fix_console
* list_cameras
* load_network
* pellet_delivery_console
* run_dlc

## Tools
The`tools` directory contains more full-featured applications.  It also includes software implementations of external 
hardware devices (e.g., head fix unit) for development and testing.

* acquisition\acquisition.py
* device\head_fix\head_fix_ui.py
* device\head_fix_server.py
* device\pellet_server.py
