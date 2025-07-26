#!/usr/bin/env bash

set -e

cd "$(dirname "${0}")"

desired_packages=(
  libhdf5-serial-dev
  libxcb-cursor0
  busybox
  can-utils
  git git-lfs
)

sudo apt-get install -y "${desired_packages[@]}"

# Disable gnome tracker service:
echo -e "\nHidden=true\n" | sudo tee --append /etc/xdg/autostart/tracker-extract.desktop /etc/xdg/autostart/tracker-miner-apps.desktop /etc/xdg/autostart/tracker-miner-fs.desktop /etc/xdg/autostart/tracker-miner-user-guides.desktop /etc/xdg/autostart/tracker-store.desktop > /dev/null

# Interval in days to check whether the filesystem is up to date in the database. 0 forces crawling anytime, -1 forces it only after unclean shutdowns, and -2 disables it entirely
gsettings set org.freedesktop.Tracker.Miner.Files crawling-interval -2  # Default: -1
# Set to false to completely disable any file monitoring
gsettings set org.freedesktop.Tracker.Miner.Files enable-monitors false # Default: true

# cleanup eventual already created db:
tracker reset --hard  # you'll have to confirm Y

# End disable gnome tracker service.

sudo usermod -a -G dialout ${USER}

#

echo "Copying target files ..."

(
  cd ./install
  sudo rsync -av ./ /
)

# enable on boot/startup:
sudo systemctl enable can_setup.service
# and already start right now too:
sudo systemctl start can_setup.service

echo "All done ok"
