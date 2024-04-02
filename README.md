# Auto Trainer

*Work in Progress* - there may be out of date or missing information.

## Requirements
Absent specific camera support, *Auto Trainer* is independent of platform and Python version >= 3.8.  Choice of cameras may 
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

* Add user to `dialout` group to access UART.  Requires reboot.

## Getting Started

The root path of the project must be added to your python path for most tools and scripts.  If using an IDE, this may be handled
for you automatically, otherwise
* Bash/Zsh: `export PYTHONPATH=$PYTHONPATH:$PWD` or `export PYTHONPATH=$PWD`
* Windows CMD: `set PYTHONPATH=%PYTHONPATH%;%CD%` or `set PYTHONPATH=%CD%`
* Windows PowerShell: `$env:PYTHONPATH += Get-Location`


## Scripts

Most of the content in `scripts` are generally lightweight utilities to determine if various components of the system are working as expected.

* acquire_image.py
  * Captures a single image frame from the camera specified by the `cameraurl`
* capture_camera.py
  * Captures 150 frames from the camera specified by the `cameraurl` argument to the location specified by `output`
* head_fix_console.py
  * A command line interface to the head fix unit.  Will log data stream to a csv file.  Supports subset of device commands.
* list_cameras.py
  * List all cameras available in the system.
* load_network.py
  * Validates loading of a DLC model with the network module
* pellet_delivery_console.py
  * A command line interface to the pellet delivery unit.  Supports a subset of device commands
* run_dlc.py
  * Sends two saved files through a DLC model with the network module

## Tools
The`tools` directory contains more full-featured applications.  It also includes software implementations of external 
hardware devices (e.g., head fix unit) for development and testing.

* acquisition\acquisition.py
  * Currently, the primary UI integrated camera, head fix, pellet delivery, and DLC model modules
* device\head_fix\head_fix_ui.py
  * Standalone UI for interfacing with the head fix unit
* device\pellet_delivery\pellet_delivery_ui.py
  * Standalone UI for interfacing with the pellet delivery unit
* device\head_fix_server.py
  * Mock server for the head fix unit for testing w/o the physical device
* device\pellet_server.py
  * Mock server for the pellet delivery unit for testing w/o the physical device


## Known Issues (partial)
* Most implementations do provide any or minimal error checking
* Only a subset of settings is remembered between settings and configuration files are not yet supported
* Cameras do not implement the offset params of the camera url
* FLIR cameras are hard-coded to a number of values until supported as params in the camera url
* There is no configuration option for the second FLIR camera to be hardware triggered
* There is no indication in the UI a camera is recording when in triggered mode
* FLIR cameras are not always properly released if a script/UI crashes or is hard-killed
