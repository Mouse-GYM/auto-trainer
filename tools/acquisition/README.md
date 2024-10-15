# Acquisition UI

## Using Configurations
Configuration files load preset values for the settings of each module (cameras, devices, analysis, output).  When 
the application starts it will load the most recent configuration file, if available and be in non-edit mode.

To make changes to module settings use the Edit Configuration toolbar button.  This will change the controls in 
each module view area to be editable where applicable.  Make the desired changes, exit edit mode (using the same
toolbar button), and then use the Save or Save As... File menu items to save the configuration to a new or
existing file.

See a complete configuration file with all allowed fields at the end of this document.  Using only a subset
of values that should not be the default is valid.

## Reference

### Menus/Toolbar Buttons

#### Toolbars
* Run/stop - start and stop acquisition and device interaction
* Edit Configuration - change the window to edit mode to change settings
* Preferences - set system level application preferences that are not part of configuration files
  * Device Name of this system
  * Log Level for the application and related services

#### Menus
* File -> Open Configuration - open an existing configuration file
* File -> Save Configuration (As) - save the current configuration file or as a new file
* View -> Diagnostics - show or hide the diagnostics panel

### Camera Control
* Video Capture - will not start the camera subprocess when not enabled
* Recode Mode - `Continuous` to record entire duration, `Trigger` to only record based on trigger events
* Video Recording - capture all frames to video files
* Image Capture - capture still images at a specified interval
* Image Capture Interval - interval for still image capture

### Head Fix Device
* Port - local device serial port
* Position - `0-100` (corresponds to `Axx` command)
* Load Cell Trigger - value above which recording will be enabled if a camera record mde is `Trigger`
* Graph - previous 5 seconds of scale data
* Header/Load Cell/Force Detector `(Dis)Engaged` indicates the state of these sensors
  * Note that this is not necessarily the instantaneous value of the sensor, but the result of
  any logic such as a minimum time to consider the load cell engaged, etc.
* Tare - Tare the load cell

### Pellet Delivery
* Port - local device serial port
* Home - device `H` command
* Load - device `P` command
* Send - device `M` command
* Release - device `R` command
* Cover - device `Q` command (not implemented)
* X - device `Ixx` command
* Y - device `Jxx` command
* Z - device `Kxx` command

### Analysis
* Enable - enable or disable pellet delivery based on marker detection
* Model - the folder containing the DLC model to use

### Metadata
* `Name` and `Notes` to be saved as part of the session metadata

### Output
* Output Location - location for recorded video files

### Log
Logs from any module that is not a subprocess.  Additional subprocess log messages can be seen at the command line.

## System Configuration
* The unit number for the output directory structure/file names can be set by editing `~/.config/Colorado/Auto Trainer.conf`
 and adding 
```
[system]
serial_number=12345
```

## Example Configuration File

Most values can be set by configuring the subsystem in the application and saving the configuration.  Others
must explicitly be added to the file.

```yaml
camera1:
  id: left
  name: Spinnaker 33199919
  url: spinnaker://33199919?fps=150&width=300&height=200&hbin=4&vbin=4&exposure=250&primary=true
  isEnabled: true
  isRecordEnabled: true
  recordMode: 1
  isStillImageCaptureEnabled: false
  stillImageCaptureInterval: 5
camera2:
  id: right
  name: Spinnaker 33199895
  url: spinnaker://33199895?fps=150&width=300&height=200&hbin=4&vbin=4&exposure=250&primary=true
  isEnabled: true
  isRecordEnabled: true
  recordMode: 1
  isStillImageCaptureEnabled: false
  stillImageCaptureInterval: 5
camera3:
  id: web
  name: ELP
  url: opencv://0?mjpeg=true&width=1920&height=1080&fps=30
  isEnabled: true
  isRecordEnabled: true
  recordMode: 0
  isStillImageCaptureEnabled: true
  stillImageCaptureInterval: 5.0
headFix:
  port: /dev/ttyACM0
  position: 0
  loadCell:
    loadTrigger: 8
    minLoadOnDuration: 0.250
    minEventDuration: 4.0
    minLoadOffDuration: 2.0
pelletDelivery:
  port: /dev/ttyACM1
  x: 0
  y: 0
  z: 0
analysis:
  model: /home/jetson/models/Christie-2024-05-02
  isEnabled: true
behavior:
  maxPelletMissingSeconds: 1.0
  maxPelletsPerSession: 15
  maxPelletsPerDay: 120

outputLocation: /home/jetson/output
```
