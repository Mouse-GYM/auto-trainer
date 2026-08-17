#!/usr/bin/env bash

set -e

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Refreshing view from origin"
if ! git fetch origin
then
  echo "WARNING: could not fetch from origin, version info may be stale" >&2
fi

if ! git update-index -q --refresh
then
  echo "WARNING: could not refresh index, version info may be stale" >&2
fi
echo

cur_branch_or_commit=$(git rev-parse --abbrev-ref HEAD)
is_clean=$(git diff-index --quiet HEAD && echo "1" || echo "0")  # NB: diff against local
local_v=$(python -m setuptools_scm 2>/dev/null || echo "NA")
latest_v=$(git describe --tags --exact-match origin/develop 2>/dev/null | sed "s/^v//")
latest_v=${latest_v:-"NA"}

is_develop_and_clean=$(test "${cur_branch_or_commit}" == "develop" -a "${is_clean}" == "1" && echo "1" || echo "0")

export AUTOTRAINER_IS_SPECIAL_BUILD=$(test "${is_develop_and_clean}" != "1" && echo "1" || echo "0")
export AUTOTRAINER_LATEST_TAG="${latest_v}"
export AUTOTRAINER_LOCAL_TAG="${local_v}"

echo
echo "Starting acquisition application .."
echo

python -m tools.acquisition.gui "${@}"
