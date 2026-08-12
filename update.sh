#!/usr/bin/env bash

set -e

echo "Updating view from origin"
git fetch origin
echo

echo "Feel free to checkout what you need. which could be:"
git branch -r --sort=-committerdate | head -5
echo

if test "$(git rev-parse --abbrev-ref HEAD)" == develop
then
    echo "Merging origin/develop .."
    git merge origin/develop
else
    printf "\n\nWARNING: develop branch not currently selected/checkout, continuing..\n\n" >&2
fi

echo "Updating project and dependencies with eager"
python -m pip install --upgrade --upgrade-strategy eager -e .
