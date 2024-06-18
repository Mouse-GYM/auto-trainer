# Acquisition UI

## Using Configurations
Configuration files load preset values for the settings of each module (cameras, devices, analysis, output).  When 
the application starts it will load the most recent configuration file, if available and be in non-edit mode.

To make changes to module settings use the Edit Configuration toolbar button.  This will change the controls in 
each module view area to be editable where applicable.  Make the desired changes, exit edit mode (using the same
toolbar button), and then use the Save or Save As... File menu items to save the configuration to a new or
existing file.

## Reference

### Menus/Toolbar Buttons

* Run/stop - start and stop acquisition and device interaction
* Manual Trigger - manually trigger recording to start or stop for triggered recording mode
* Edit Configuration - change the window to edit mode to change settings
* File -> Open Configuration - open an existing configuration file
* File -> Save Configuration (As) - save the current configuration file or as a new file
* View -> Diagnostics - show or hide the diagnostics panel

### Camera Control
* Enabled - will not start the camera subprocess when not enabled
* Record - will not record when not enabled
* Recode Mode - `Continuous` to record entire duration, `Trigger` to only record based on trigger events

### Head Fix Device
* Port - local device serial port
* Position - 0-100 (corresponds to Axx command)
* Load Cell Trigger - value above which recording will be enabled if a camera record mde is `Trigger`
* Graph - previous 5 seconds of scale data

### Pellet Delivery
* Port - local device serial port
* Home - device `H` command
* Load - device `P` command
* Send - device `M` command
* Release - device `R` command
* X - device `Ixx` command
* Y - device `Jxx` command
* Z - device `Kxx` command

### Analysis
* Enable - enable or disable pose analysis
* Model - the folder containing the DLC model to use

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