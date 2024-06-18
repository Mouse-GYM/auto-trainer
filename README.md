# Auto Trainer

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

#### arm64 example

```
gunzip spinnaker-3.2.0.57-arm64-pkg-20.04.tar.gz 
tar -xvf spinnaker-3.2.0.57-arm64-pkg-20.04.tar 
cd spinnaker-3.2.0.57-arm64/
sudo apt-get install libusb-1.0-0 (no-op was already the most recent)
sudo apt-get --fix-broken install
sudo sh install_spinnaker_arm.sh
```
## Platform Specific Requirements 

### Jetson

* Ubuntu 20 and JetPack 5.1.2 installed from the SDK manager
  * Later 5.1.x JetPack if that is all that is available may be ok, but is untested
* Add user to `dialout` group `sudo usermod -a -G dialout [username]`.  Requires logout or reboot depending on UART.
* Access to two UARTs for full feature support requires at least additional port via USB->serial interface
* HDF5
* xcb-cursor

*HDF5*

`sudo apt-get install libhdf5-serial-dev`

 *xcb-cursor*

`sudo apt-get install libxcb-cursor0 `


## Package Installation

Create a Conda environment if needed or activate an existing one:

`conda create -n "auto-trainer-1" python=3.8`

Clone https://github.com/Mouse-GYM/auto-trainer.

`git clone https://github.com/Mouse-GYM/auto-trainer.git .`

Activate an appropriate branch, *e.g.,*

`git checkout develop`

From the repository directory perform the following Python package installation steps.

`pip install -r requirements.txt`

`conda install --channel=conda-forge ffmpeg=6.0.0`

### Tensorflow
Fix the tensorflow install depending on the platform:

*Jetson Only*

`pip uninstall tensorflow`

`pip install --extra-index-url https://developer.download.nvidia.com/compute/redist/jp/v512 tensorflow==2.12.0+nv23.06`

*Note:* There will be a pip dependency error message that does not affect the current functionality.

### FLIR

To include support for Teledyne/Blackfly cameras, install the appropriate wheel for your platform, *e.g.,* 

`pip install ./library/spinnaker_python-3.2.0.57-cp38-cp38-linux_aarch64.whl`

or 

`pip install ./library/spinnaker_python-3.2.0.57-cp38-cp38-linux_x86_64.whl`

or

`pip install .\library\spinnaker_python-3.2.0.57-cp38-cp38-win_amd64.whl`

### LD_PRELOAD

A command similar to following must be used or added to `.bashrc`/`.bash_profile`

```shell
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libffi.so.7:/usr/lib/aarch64-linux-gnu/libgomp.so.1:/lib/aarch64-linux-gnu/libGLdispatch.so.0:/home/$USER/anaconda3/envs/auto-trainer-1/lib/python3.8/site-packages/sklearn/__check_build/../
../scikit_learn.libs/libgomp-d22c30c5.so.1.0.0:/home/$USER/anaconda3/envs/auto-trainer-1/lib/python3.8/site-packages/torch/lib/libgomp-d22c30c5.so.1

```

The exact filenames of the last two in particular may be slightly different based on versioning.  There will be an
error message in the console with the exact filename if it is different from the above.

## Applications

* Auto Trainer
  *  The local user interface for integrated camera, head fix, pellet delivery, and pose inference modules 
  * `python auto-trainer-local.py`
* Head Fix
  * Standalone UI for interfacing with the head fix system
  * `python head_fix.py`
* Pellet Delivery
  * Standalone UI for interfacing with the pellet delivery system
  * `python pellet_delivery.py`

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
* load_dlc_model.py
  * Validates loading of a DLC model with the network module
* pellet_delivery_console.py
  * A command line interface to the pellet delivery unit.  Supports a subset of device commands
* run_dlc_model.py
  * Sends two saved files through a DLC model with the network module

## Additional Tools

* auto-trainer-device\tools\head_fix_server.py
  * Mock server for the head fix unit for testing w/o the physical device
  * `python auto-trainer-device\tools\head_fix_server.py`
    * specify the serial port, `/dev/ttyACM1`, `COM4`, etc...
    * specify measurement update frequency `-f 100` for 100 Hz
    * specify random data vs. fixed `-r`
    * specify firmware version to report `-v 3.0`
  * whether set to random or fixed data, use the `s`, `d`, `a`, `t`, or `h` commands followed by the value to change those measurement values
* auto-trainer-device\tools\pellet_server.py
  * Mock server for the pellet delivery unit for testing w/o the physical device
  * `python auto-trainer-device\tools\pellet_server.py`
    * specify the serial port, `/dev/ttyACM1`, `COM4`, etc...
    * specify firmware version to report `-v 3.0`

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

## Testing

PyTest testing is supported and configured via `conftest.py`.

Individual namespace packages (*e.g,* `auto-trainer-core`) contain a `tests` directory.  There are also unit and functional
tests for high-level functionality in the applications and that combine elements of multiple packages.

Tests that are longer or require additional configuration are marked as `@pytest.mark.functional` and are not run
by default.

PyTest is not installed with via the default requirements.txt.  To enable testing use

`pip install -r requirements-test.txt`

Run all default tests from the root directory:

`pytest`

Run all tests, including functional, from the root directory:

`pytest --functional`

To limit testing to an individual namespace package, change your working directory to that package and use the same commands

## Known Issues (partial)
* Most implementations do not provide any or provide only minimal error checking
* Only a subset of settings is remembered between settings and configuration files are not yet supported
* FLIR cameras are not always properly released if a script/UI crashes or is hard-killed
* Acquisition UI uses a hardcoded list of cameras in `cameras.txt` in the root directory
  * Entries are of the form `name, camera-url` *e.g.,* `Spinnaker 23199895, spinnaker://23199895?width=300&height=200`
* There is no feedback during the long pause to start up and tear down camera capture processes; the UI appears blocked
