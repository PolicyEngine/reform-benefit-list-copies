"""Baseline neutrality of policyengine-us#10662: the branch's SPM list is main's.

Usage: python compare_lists.py MAIN_TREE AFTER_TREE

Main defines spm_unit_benefits with a BENEFITS list literal inside its formula,
then appends assigned_aca_ptc under the flat tax's deduct_ptc switch and
spm_unit_capped_housing_subsidy unless gov.hud.abolition. The branch reads the
list from gov.household.spm_unit_benefits and appends the same two names under
the same two conditions.

The script parses both formulas with ast and checks that
- every dated value of the branch's list parameter equals main's BENEFITS, in
  main's order;
- both formulas append the same names, in the same order, under the same
  conditions (with parameters(period) written as p on both sides);
- household_benefits.yaml, which main already kept as a parameter, holds the
  same dated values on both trees.

It needs only PyYAML, and exits 1 on any difference.
"""

import ast
import sys
from pathlib import Path

import yaml

FORMULA = "policyengine_us/variables/household/income/spm_unit/spm_unit_benefits.py"
SPM_LIST = "policyengine_us/parameters/gov/household/spm_unit_benefits.yaml"
HOUSEHOLD_LIST = "policyengine_us/parameters/gov/household/household_benefits.yaml"


def formula_of(tree):
    module = ast.parse((tree / FORMULA).read_text())
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "formula":
            return node
    raise SystemExit(f"{tree / FORMULA}: no formula")


def list_literal(formula):
    """Main's BENEFITS = [...]; None when the formula has no list literal."""
    for node in ast.walk(formula):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.List)
            and all(isinstance(e, ast.Constant) for e in node.value.elts)
        ):
            return [e.value for e in node.value.elts]
    return None


def appends(formula):
    """(condition, name) for each .append("name") under an if, in source order."""
    found = []
    for node in ast.walk(formula):
        if not isinstance(node, ast.If):
            continue
        condition = ast.unparse(node.test).replace("parameters(period)", "p")
        for statement in node.body:
            call = getattr(statement, "value", None)
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "append"
                and isinstance(call.args[0], ast.Constant)
            ):
                found.append((node.lineno, condition, call.args[0].value))
    return [(condition, name) for _, condition, name in sorted(found)]


def dated_values(path):
    """{date string: members}. BaseLoader keeps the dates as strings, since
    PyYAML cannot read year 0000 as a date."""
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)["values"]


def main():
    main_tree, after_tree = (Path(p) for p in sys.argv[1:3])
    failures = []

    benefits = list_literal(formula_of(main_tree))
    if benefits is None:
        raise SystemExit(f"{main_tree / FORMULA}: no BENEFITS list literal")
    if list_literal(formula_of(after_tree)) is not None:
        failures.append("the branch formula still holds a list literal")
    values = dated_values(after_tree / SPM_LIST)
    print(f"main BENEFITS: {len(benefits)} programs")
    for date, members in values.items():
        same = members == benefits
        print(f"branch {SPM_LIST.rsplit('/', 1)[1]} {date}: {len(members)} programs, "
              f"{'same programs in the same order' if same else 'DIFFERENT'}")
        if not same:
            missing = [n for n in benefits if n not in members]
            extra = [n for n in members if n not in benefits]
            moved = [] if missing or extra else [
                (i, a, b) for i, (a, b) in enumerate(zip(benefits, members)) if a != b
            ][:5]
            failures.append(f"{date}: missing {missing}, extra {extra}, first reorderings {moved}")

    main_appends, after_appends = appends(formula_of(main_tree)), appends(formula_of(after_tree))
    print(f"main appends: {main_appends}")
    print(f"branch appends: {after_appends}")
    if main_appends != after_appends:
        failures.append("the formulas append different names or under different conditions")

    main_household = dated_values(main_tree / HOUSEHOLD_LIST)
    after_household = dated_values(after_tree / HOUSEHOLD_LIST)
    same = main_household == after_household
    print(f"household_benefits.yaml: {len(main_household)} dated values, "
          f"{'equal on both trees' if same else 'DIFFERENT'}")
    if not same:
        failures.append("household_benefits.yaml differs between the trees")

    print("PASS" if not failures else "FAIL")
    for failure in failures:
        print(f"- {failure}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
