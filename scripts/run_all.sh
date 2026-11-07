#!/bin/bash
# Runs the twelve microsimulations behind runs/<policy>_<side>.json, one process
# each. MAIN_TREE and AFTER_TREE name policyengine-us checkouts at e53b426082 and
# ee75695b5a, and PY names a Python with policyengine-us's dependencies.
# reform_lists.py skips any year its output file already holds.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${MAIN_TREE:?set MAIN_TREE}" "${AFTER_TREE:?set AFTER_TREE}" "${PY:?set PY}"
export AFTER_TREE
for spec in "tx_rebate 2027" "end_child_poverty_act 2027" \
  "edaa_end_child_poverty_act 2027" "boost_middle_class_tax_credit 2027" \
  "baseline 2027" "end_child_poverty_act 2024"; do
  read -r policy year <<<"$spec"
  PYTHONPATH="$AFTER_TREE" "$PY" scripts/reform_lists.py "runs/${policy}_after.json" "$policy" "$year"
  PYTHONPATH="$MAIN_TREE" "$PY" scripts/reform_lists.py "runs/${policy}_before.json" "$policy" "$year"
done
