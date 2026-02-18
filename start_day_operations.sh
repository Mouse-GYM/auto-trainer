#!/usr/bin/env bash

set -e

echo "Updating view from origin"
git fetch origin
echo

echo "Feel free to checkout what you need. which can be:"
git branch -r | grep origin
echo

echo "Checking out origin/develop .."
git checkout origin/develop
echo
