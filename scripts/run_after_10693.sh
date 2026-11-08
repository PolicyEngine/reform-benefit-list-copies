#!/bin/bash
# Runs the ten 2026 microsimulations behind runs/after-10693/<policy>_<side>.json,
# one process each: current law and the four reforms, on main after
# policyengine-us#10693 (MAIN_TREE) and on #10662 merged with that main
# (AFTER_TREE). PY names a Python with policyengine-us's dependencies.
# reform_lists.py skips any year its output file already holds.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${MAIN_TREE:?set MAIN_TREE}" "${AFTER_TREE:?set AFTER_TREE}" "${PY:?set PY}"
export AFTER_TREE
mkdir -p runs/after-10693
for policy in tx_rebate end_child_poverty_act edaa_end_child_poverty_act \
  boost_middle_class_tax_credit baseline; do
  PYTHONPATH="$AFTER_TREE" "$PY" scripts/reform_lists.py "runs/after-10693/${policy}_after.json" "$policy" 2026
  PYTHONPATH="$MAIN_TREE" "$PY" scripts/reform_lists.py "runs/after-10693/${policy}_before.json" "$policy" 2026
done
