"""Mutation check of the reform guards in test_aggregate_list_integrity.py.

Usage: python mutate_guard.py TREE   ($PY, if set, names the Python that runs pytest)

TREE is a scratch git worktree; each mutant edits it, runs the integrity test
file, and restores it with git checkout and git clean. A mutant that should
fail the guard must fail it; the controls must pass.
"""

import os
import subprocess
import sys
from pathlib import Path

tree = Path(sys.argv[1])
# The Python that runs pytest: $PY, else the one running this script.
PY = os.environ.get("PY", sys.executable)
TEST = "policyengine_us/tests/test_aggregate_list_integrity.py"
NEW = "policyengine_us/reforms/mutant_reform.py"


def write(path, text):
    (tree / path).write_text(text)


def replace(path, old, new):
    p = tree / path
    text = p.read_text()
    assert old in text, (path, old)
    p.write_text(text.replace(old, new, 1))


def drop_tx_rebate():
    replace(
        "policyengine_us/tests/test_reform_benefit_lists.py",
        '    "tx_rebate": (tx_rebate, "tx_rebate"),\n',
        "",
    )


MUTANTS = {
    # name: (edit, should_fail)
    "REFORMS forgets tx_rebate": (drop_tx_rebate, True),
    "new reform updates the SPM list directly": (
        lambda: write(
            NEW,
            "def modify_parameters(parameters):\n"
            "    parameters.gov.household.spm_unit_benefits.update(\n"
            "        start='2024-01-01', value=['snap']\n"
            "    )\n",
        ),
        True,
    ),
    "new reform reaches household_state_benefits through an alias": (
        lambda: write(
            NEW,
            "def modify_parameters(parameters):\n"
            "    household = parameters.gov.household\n"
            "    lists = household.household_state_benefits\n"
            "    return lists\n",
        ),
        True,
    ),
    "new reform reaches a list by string path": (
        lambda: write(
            NEW,
            "def modify_parameters(parameters):\n"
            "    return parameters.get_child('gov.household.household_local_benefits')\n",
        ),
        True,
    ),
    "new reform copies household_state_benefits": (
        lambda: write(
            NEW,
            "def create():\n"
            "    class household_state_benefits(Variable):\n"
            "        adds = ['ca_capi']\n",
        ),
        True,
    ),
    "new reform copies household_health_benefits": (
        lambda: write(
            NEW,
            "def create():\n"
            "    class household_health_benefits(Variable):\n"
            "        pass\n",
        ),
        True,
    ),
    "control: reads totals by variable name, docstring names a list": (
        lambda: write(
            NEW,
            '"""Reads gov.household.spm_unit_benefits only as a variable."""\n'
            "def formula(spm_unit, period, parameters):\n"
            "    return spm_unit('spm_unit_benefits', period) + spm_unit(\n"
            "        'household_benefits', period\n"
            "    )\n",
        ),
        False,
    ),
    "control: no change": (lambda: None, False),
}


def run():
    result = subprocess.run(
        [str(PY), "-m", "pytest", "-p", "no:cacheprovider", "-q", "-x", TEST],
        cwd=tree,
        env={"PYTHONPATH": str(tree), "PATH": "/usr/bin:/bin", "PYTHONWARNINGS": "ignore",
             "HOME": str(Path.home())},
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip().splitlines()[-1:]


def restore():
    subprocess.run(["git", "-C", str(tree), "checkout", "--", "."], check=True)
    subprocess.run(["git", "-C", str(tree), "clean", "-fdq", "policyengine_us"], check=True)


failures = 0
for name, (edit, should_fail) in MUTANTS.items():
    restore()
    edit()
    code, tail = run()
    failed = code != 0
    ok = failed == should_fail
    failures += not ok
    print(f"{'ok  ' if ok else 'MISS'} {name}: exit {code} {tail}", flush=True)
restore()
print(f"{len(MUTANTS) - failures} of {len(MUTANTS)} as expected")
sys.exit(1 if failures else 0)
