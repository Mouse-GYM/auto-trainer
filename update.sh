#!/usr/bin/env bash

set -e

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Updating view from origin"
git fetch origin
echo

echo "Feel free to checkout what you need. which could be:"
git branch -r --sort=-committerdate | head -5
echo

if test "$(git rev-parse --abbrev-ref HEAD)" == develop
then
    echo "Merging origin/develop .."
    if ! git merge --ff-only origin/develop; then
        printf "\n\nWARNING: local develop has diverged from origin/develop.\n" >&2
        printf "Code not updated; resolve manually before relying on this rig.\n\n" >&2
    fi
else
    printf "\n\nWARNING: develop branch not currently selected/checkout, continuing..\n\n" >&2
fi

echo "Updating project and dependencies with eager"
python -m pip install --upgrade --upgrade-strategy eager -e .
