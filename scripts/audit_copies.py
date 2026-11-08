"""List what each reform copy of the benefit lists leaves out, by year block.

Usage: python audit_copies.py REPO REV [REV ...]

For each git revision, reads the four reform modules that redefine
household_benefits or spm_unit_benefits, and compares each copy with the
baseline at that revision:

- household_benefits: every dated block of
  parameters/gov/household/household_benefits.yaml (the baseline formula reads
  the parameter and drops housing_assistance under gov.hud.abolition);
- spm_unit_benefits: the list in variables/.../spm_unit_benefits.py, or the
  parameter parameters/gov/household/spm_unit_benefits.yaml where a revision
  has one, plus the names the formula appends under a condition.

A copy that reads the parameter itself has no omissions by construction of
its source, and the script says so instead of comparing. Everything here comes
from parsing the files at each revision; nothing is run.
"""

import ast
import subprocess
import sys

import yaml

REFORMS = {
    "tx_rebate": "policyengine_us/reforms/states/tx/rebate/tx_rebate.py",
    "end_child_poverty_act": "policyengine_us/reforms/congress/tlaib/end_child_poverty_act.py",
    "edaa_end_child_poverty_act": (
        "policyengine_us/reforms/congress/tlaib/economic_dignity_for_all_agenda/"
        "edaa_end_child_poverty_act.py"
    ),
    "boost_middle_class_tax_credit": (
        "policyengine_us/reforms/congress/tlaib/boost/boost_middle_class_tax_credit.py"
    ),
}
# Each reform's own payment, which its copy adds on purpose.
OWN = {
    "tx_rebate": {"tx_rebate"},
    "end_child_poverty_act": {"ecpa_child_benefit"},
    "edaa_end_child_poverty_act": {"ecpa_child_benefit"},
    "boost_middle_class_tax_credit": {
        "boost_middle_class_tax_credit",
        "boost_middle_class_tax_credit_paid_through_ssa",
    },
}
HOUSEHOLD_YAML = "policyengine_us/parameters/gov/household/household_benefits.yaml"
SPM_YAML = "policyengine_us/parameters/gov/household/spm_unit_benefits.yaml"
SPM_PY = "policyengine_us/variables/household/income/spm_unit/spm_unit_benefits.py"
AGGREGATES = ("household_benefits", "spm_unit_benefits")


def show(repo, rev, path):
    result = subprocess.run(
        ["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else None


def strings(node):
    return [
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]


def read_formula(class_node, source):
    """The list a formula sums, what it appends and under which condition,
    and whether it starts from a parameter."""
    members, conditional, reads = [], [], None
    for node in ast.walk(class_node):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "BENEFITS" for t in node.targets
        ):
            if isinstance(node.value, ast.List):
                members = strings(node.value)
            elif "parameters(period)" in ast.get_source_segment(source, node.value):
                reads = ast.get_source_segment(source, node.value)
    # Appends: unconditional when the call sits directly in the function body.
    for function in [n for n in ast.walk(class_node) if isinstance(n, ast.FunctionDef)]:
        for statement in function.body:
            for node in ast.walk(statement):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "BENEFITS"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    name = node.args[0].value
                    if isinstance(statement, ast.If):
                        test = ast.get_source_segment(source, statement.test)
                        conditional.append((name, test))
                    else:
                        members.append(name)
    return members, conditional, reads


def copies(source):
    tree = ast.parse(source)
    return {
        node.name: read_formula(node, source)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name in AGGREGATES
    }


def household_blocks(repo, rev):
    raw = yaml.load(show(repo, rev, HOUSEHOLD_YAML), Loader=yaml.BaseLoader)
    return {date: members for date, members in raw["values"].items()}


def spm_baseline(repo, rev):
    """The SPM list and its conditional appends at a revision."""
    yaml_text = show(repo, rev, SPM_YAML)
    source = show(repo, rev, SPM_PY)
    found = copies(source)["spm_unit_benefits"]
    if yaml_text:
        raw = yaml.load(yaml_text, Loader=yaml.BaseLoader)
        blocks = {date: members for date, members in raw["values"].items()}
        return blocks, found[1], "parameter"
    return {"(Python list)": found[0]}, found[1], "python"


def main():
    repo, revs = sys.argv[1], sys.argv[2:]
    for rev in revs:
        commit = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--short=10", rev],
            capture_output=True,
            text=True,
        ).stdout.strip()
        print(f"## {rev} ({commit})\n")
        household = household_blocks(repo, rev)
        spm, spm_conditional, spm_kind = spm_baseline(repo, rev)
        print(
            "Baseline: household_benefits blocks "
            + ", ".join(f"{d} ({len(m)} members)" for d, m in household.items())
            + f"; spm_unit_benefits {spm_kind} "
            + ", ".join(f"{d} ({len(m)} members)" for d, m in spm.items())
            + " plus "
            + ", ".join(f"`{n}` if `{c}`" for n, c in spm_conditional)
            + ".\n"
        )
        for reform, path in REFORMS.items():
            source = show(repo, rev, path)
            found = copies(source)
            if not found:
                print(f"- **{reform}**: redefines neither aggregate.\n")
                continue
            for aggregate, (members, conditional, reads) in sorted(found.items()):
                label = f"**{reform}** `{aggregate}`"
                if reads:
                    extra = [
                        n for n in members if n not in OWN[reform]
                    ]
                    print(
                        f"- {label}: reads `{reads}`, then appends "
                        f"{sorted(set(members))}"
                        + (f" (beyond its own payment: {extra})" if extra else "")
                        + "; no omission by construction.\n"
                    )
                    continue
                baseline_blocks = household if aggregate == "household_benefits" else spm
                repeated = sorted({n for n in members if members.count(n) > 1})
                print(f"- {label}: {len(members)} names in the copy.")
                for date, base in baseline_blocks.items():
                    missing = [n for n in base if n not in members]
                    extra = [
                        n for n in members if n not in base and n not in OWN[reform]
                    ]
                    print(
                        f"  - vs baseline {date}: leaves out {len(missing)}"
                        + (f": {', '.join(missing)}" if missing else "")
                        + (
                            f"; adds {len(extra)} the baseline lacks: {', '.join(extra)}"
                            if extra
                            else ""
                        )
                    )
                if aggregate == "spm_unit_benefits":
                    base_conditional = dict(spm_conditional)
                    copy_conditional = dict(conditional)
                    if base_conditional != copy_conditional:
                        print(
                            f"  - conditional appends differ: baseline "
                            f"{spm_conditional}, copy {conditional}"
                        )
                if repeated:
                    print(f"  - repeats {repeated}")
                print()


if __name__ == "__main__":
    main()
