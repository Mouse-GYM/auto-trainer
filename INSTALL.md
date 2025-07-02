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
* We want to disable the "tracker" gnome indexing service:
  * It's unnecessary to the app, and can induce some bad overhead on CPU and IO.
  * See, for instance: https://askubuntu.com/a/348692
```bash
echo -e "\nHidden=true\n" | sudo tee --append /etc/xdg/autostart/tracker-extract.desktop /etc/xdg/autostart/tracker-miner-apps.desktop /etc/xdg/autostart/tracker-miner-fs.desktop /etc/xdg/autostart/tracker-miner-user-guides.desktop /etc/xdg/autostart/tracker-store.desktop > /dev/null

# Interval in days to check whether the filesystem is up to date in the database. 0 forces crawling anytime, -1 forces it only after unclean shutdowns, and -2 disables it entirely
gsettings set org.freedesktop.Tracker.Miner.Files crawling-interval -2  # Default: -1
# Set to false to completely disable any file monitoring
gsettings set org.freedesktop.Tracker.Miner.Files enable-monitors false # Default: true

# cleanup eventual already created db:
tracker reset --hard  # you'll have to confirm Y
```

* Add user to `dialout` group `sudo usermod -a -G dialout [username]`.  Requires logout or reboot depending on UART.
* Access to two UARTs for full feature support requires at least additional port via USB->serial interface
* HDF5
* xcb-cursor

*HDF5*

`sudo apt-get install libhdf5-serial-dev`

 *xcb-cursor*

`sudo apt-get install libxcb-cursor0`


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
