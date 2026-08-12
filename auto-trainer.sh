#!/usr/bin/env bash

set -exv

echo "Refreshing view from origin"
git fetch origin
echo

cur_branch_or_commit=$(git rev-parse --abbrev-ref HEAD)
is_clean=$(git diff-index --quiet HEAD && echo "1" || echo "0")  # NB: diff against local
latest_v=$(git describe --tags origin/develop --match "v*")  # exact origin/latest git tag
local_v=$(git describe --tags --match "v*")  # NB: this gives git tag of whatever is currently checkout

is_develop_and_clean=$(test "${cur_branch_or_commit}" == "develop" -a "${is_clean}" == "1" && echo "1" || echo "0")

export AUTOTRAINER_IS_SPECIAL_BUILD=$(test "${is_develop_and_clean}" != "1" && echo "1" || echo "0")
export AUTOTRAINER_LATEST_TAG="${latest_v}"
export AUTOTRAINER_LOCAL_TAG="${local_v}"

python -m tools.acquisition.gui "${@}"
