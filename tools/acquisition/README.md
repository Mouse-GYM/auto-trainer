## Acquisition UI

### Toolbar Buttons

* Run/stop - start and stop acquisition and device interaction
* Manual Trigger - manually trigger recording to start or stop for triggered recording mode

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

### Output
* Output Location - location for recorded video files

### Log
Logs from any module that is not a subprocess.  Additional subprocess log messages can be seen at the command line.

### Temporary Tricks (april-cleanup branch only)
* The three cameras will be set to the first three entries in cameras.txt (if there are enough entries)
* If the serial ports for head/pellet were set in a previous run and still available, connections will begin at startup
* The unit number for the output directory structure/file names can be set by editing `~/.config/Colorado/Auto Trainer.conf`
 and adding 
```
[system]
serial_number=12345
```