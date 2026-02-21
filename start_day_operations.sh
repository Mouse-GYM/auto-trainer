#!/usr/bin/env bash

set -e

echo "Updating view from origin"
git fetch origin
echo

echo "Feel free to checkout what you need. which could be:"
git branch -r --sort=-committerdate | head -5

echo

echo "Checking out origin/develop .."
git checkout origin/develop
echo
