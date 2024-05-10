# Auto Trainer

*Work in Progress* - there may be out of date or missing information.

## Requirements
Absent specific camera support, *Auto Trainer* is independent of platform and Python version >= 3.8.  Choice of cameras may 
place requirements on platform or Python version.

### System Installs/Requirements
#### Anaconda
Anaconda is required for full feature support, although most functionality will work in a vanilla venv.  Tested with `Anaconda3-2023.09-0-Linux-aarch64.sh`.

#### HDF5
`sudo apt-get install libhdf5-serial-dev`

#### xcb-cursor
`sudo apt-get install libxcb-cursor0 `

### Teledyne/Blackfly Camera Support

* These cameras require installation of version 3 of the Spinnaker SDK/runtime for your platform.
* Platforms are limited to Windows and Ubuntu 20.04
* Python version is limited to 3.8

#### arm64 example

```
gunzip spinnaker-3.2.0.57-arm64-pkg-20.04.tar.gz 
tar -xvf spinnaker-3.2.0.57-arm64-pkg-20.04.tar 
cd spinnaker-3.2.0.57-arm64/
sudo apt-get install libusb-1.0-0 (no-op was already the most recent)
sudo apt-get --fix-broken install
sudo sh install_spinnaker_arm.sh
```

## Installation
Create a default installation without specific camera support:

`pip install -r requirements.txt`

To include support for Teledyne/Blackfly cameras, install the appropriate wheel for your platform, *e.g.,* 

`pip install ./library/spinnaker_python-3.2.0.57-cp38-cp38-linux_aarch64.whl`

Wheels for supported platforms are included in `library/`.

To enable video recording

`conda install --channel=conda-forge ffmpeg=6.0.0`

### Platform Specific Installation 

#### Jetson

* Ubuntu 20 and JetPack 5.1.2 install from the SDK manager
  * Later 5.1.x JetPack if that is all that is available may be ok, but is untested
* Add user to `dialout` group `sudo usermod -a -G dialout [username]`.  Requires logout or reboot depending on UART.
* Access to two UARTs for full feature support requires at least additional port via USB->serial interface

## Getting Started

The root path of the project must be added to your python path for most tools and scripts.  If using an IDE, this may be handled
for you automatically, otherwise
* Bash/Zsh: `export PYTHONPATH=$PYTHONPATH:$PWD` or `export PYTHONPATH=$PWD`
* Windows CMD: `set PYTHONPATH=%PYTHONPATH%;%CD%` or `set PYTHONPATH=%CD%`
* Windows PowerShell: `$env:PYTHONPATH += Get-Location`


## Scripts

Most of the content in `scripts` are lightweight utilities to determine if various components of the system are working as expected.

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

## Camera URLs
Several scripts and tools use camera URLs to specify the camera and camera properties.  The URLs have the form

`<cameratype>://<cameraid>?<properties>`

`cameratype` is one of `opencv`, `spinnaker`, `playback`, or `random`.

`cameraid` depends on the camera type.
* Spinnaker - camera serial number
* OpenCV - camera index
* Playback - file name
* Random Image - n/a, enter anything

`properties` are URL query string parameters in the form `prop=value`.  Multiple properties are separated by `&`.

Supported properties:
* `fps` - frame rate
* `width` - width in pixels
* `height` - height in pixels
* `offsetx` - x offset in pixels (FLIR only)
* `offsety` - y offset in pixels (FLIR only)
* `exposure` - exposure time (FLIR only)
* `hbin` - horizontal binning (FLIR only)
* `vbin` - vertical binning (FLIR only)
* `primary` - marks as primary for hardware configuration (true/false) (FLIR only)
* `secondary` - marks as secondary for hardware configuration (true/false) (FLIR only)

All properties are optional and only applicable on cameras that support the property.  Spinnaker is currently the only
camera type that supports primary/secondary where it is used to configure hardware triggering.

## Known Issues (partial)
* Most implementations do not provide any or minimal error checking
* Only a subset of settings is remembered between settings and configuration files are not yet supported
* There is no indication in the UI a camera is recording when in triggered mode
* FLIR cameras are not always properly released if a script/UI crashes or is hard-killed
* Acquisition UI uses a hardcoded list of cameras in `cameras.txt` in the root directory
  * Entries are of the form `name, camera-url` *e.g.,* `Spinnaker 23199895, spinnaker://23199895?width=300&height=200`
* There is no feedback during the long pause to start up and tear down camera capture processes; the UI appears blocked
