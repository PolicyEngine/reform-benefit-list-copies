#!/bin/bash
# Runs the PR's four reform YAML files against main's code: copies them into the
# checkout at MAIN_TREE, runs each with policyengine-core, and removes them again.
# HEAD_TREE names a checkout of the PR head, and PY a Python with policyengine-us's
# dependencies.
set -uo pipefail
: "${MAIN_TREE:?set MAIN_TREE}" "${HEAD_TREE:?set HEAD_TREE}" "${PY:?set PY}"
T=policyengine_us/tests/policy/reform
cd "$MAIN_TREE"
for f in tx_rebate end_child_poverty_act edaa_end_child_poverty_act boost; do
  cp "$HEAD_TREE/$T/${f}_counts_every_baseline_benefit.yaml" "$T/"
  echo "=== $f"
  PYTHONPATH="$MAIN_TREE" "$(dirname "$PY")/policyengine-core" test "$T/${f}_counts_every_baseline_benefit.yaml" -c policyengine_us 2>&1
  rm -f "$T/${f}_counts_every_baseline_benefit.yaml"
done
git status --short
