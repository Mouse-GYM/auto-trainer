#!/usr/bin/env bash

auto_trainer_pkgs=( $(pip list | egrep "^auto-trainer" | awk '{print $1}') )

echo "Currently installed auto-trainer packages:"
for pkg in ${auto_trainer_pkgs[@]}
do
  echo "$pkg"
done

is_in_pkgs() {
  for pkg in ${auto_trainer_pkgs[@]}
  do
    if [[ "${pkg}" = "$1" ]] ; then return 0 ; fi
  done
  return 1
}

bads=()
for sub_prj in $(cat auto_trainer_projects_order.txt)
do
  if is_in_pkgs "${sub_prj}"
  then
    bads+=("${sub_prj}")
  fi
done

if [[ "${bads}" != "" ]]
then
  echo "Found ${bads[@]} installed as independent package(s), this is abnormal" >&2
  exit 1
fi
