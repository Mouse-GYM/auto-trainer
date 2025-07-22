#!/usr/bin/env bash

set -e  # exit with error on any error

# Sets up CAN drivers on the Jetson AGX Orin Development Kit
# More information: https://docs.nvidia.com/jetson/archives/r34.1/DeveloperGuide/text/HR/ControllerAreaNetworkCan.html

# Run this script as sudo
if [ "$EUID" -ne 0 ]
  then echo "Please run as root"
  exit 1
fi

# set registers to enable CAN ports
echo "Setting registers to enable CAN ports"
busybox devmem 0x0c303018 w 0x458 # can0 din
busybox devmem 0x0c303010 w 0x400 # can0 dout
busybox devmem 0x0c303008 w 0x458 # can1 din
busybox devmem 0x0c303000 w 0x400 # can0 dout

# load CAN kernel drivers
echo "Loading CAN kernel drivers"
modprobe can
modprobe can_raw
modprobe mttcan

# set interface properties
echo "Setting CAN interface properties"
ip link set can0 up type can bitrate 1000000 dbitrate 5000000 berr-reporting on fd on
ip link set can1 up type can bitrate 1000000 dbitrate 5000000 berr-reporting on fd on
