#!/usr/bin/env bash

set -e

echo "Updating view from origin"
git fetch origin

echo "Checking out origin/develop .."
git checkout origin/develop
