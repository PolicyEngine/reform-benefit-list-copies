"""Compare each reform's copied benefit lists with the baseline lists, by AST.

Usage: python3 copy_gaps.py TREE

TREE is a policyengine-us checkout from before #10662. Parses source only and
imports nothing, so it adds no load. Prints, per reform, what each copy lacks
and what it adds compared with the baseline.

gaps(TREE) returns the same comparison under default parameters (the UBI
Center flat tax's deduct_ptc off, gov.hud.abolition off), for the renderer's
check that each reform's change in an aggregate equals the totals of these
programs.
"""

import ast
import re
import sys
from pathlib import Path

REFORMS = {
    "tx_rebate": "reforms/states/tx/rebate/tx_rebate.py",
    "end_child_poverty_act": "reforms/congress/tlaib/end_child_poverty_act.py",
    "edaa_end_child_poverty_act": (
        "reforms/congress/tlaib/economic_dignity_for_all_agenda/"
        "edaa_end_child_poverty_act.py"
    ),
    "boost_middle_class_tax_credit": (
        "reforms/congress/tlaib/boost/boost_middle_class_tax_credit.py"
    ),
}
# Each reform's own benefit. Both versions count it, so it is no gap.
OWN = {
    "tx_rebate": {"tx_rebate"},
    "end_child_poverty_act": {"ecpa_child_benefit"},
    "edaa_end_child_poverty_act": {"ecpa_child_benefit"},
    "boost_middle_class_tax_credit": {
        "boost_middle_class_tax_credit",
        "boost_middle_class_tax_credit_paid_through_ssa",
    },
}
# Appends that only the flat tax's deduct_ptc switch turns on.
DEDUCT_PTC_APPENDS = {"aca_ptc", "assigned_aca_ptc"}


def string_lists(node):
    """Every list literal of strings under a node, with the name it binds to."""
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and isinstance(child.value, ast.List):
            values = child.value.elts
            if values and all(
                isinstance(v, ast.Constant) and isinstance(v.value, str)
                for v in values
            ):
                name = getattr(child.targets[0], "id", "?")
                found.append((name, [v.value for v in values]))
    return found


def appended(node):
    """Names a node appends with .append("name")."""
    names = []
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "append"
            and child.args
            and isinstance(child.args[0], ast.Constant)
            and isinstance(child.args[0].value, str)
        ):
            names.append(child.args[0].value)
    return names


def classes(path, name):
    """Every class with this name in a file, however deeply it nests."""
    source = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(source)
        if isinstance(node, ast.ClassDef) and node.name == name
    ]


def yaml_block_members(path):
    """Members of the newest dated block of a list parameter, by regex."""
    text = path.read_text()
    blocks = re.split(r"^\s*(\d{4}-\d{2}-\d{2}):\s*$", text, flags=re.M)
    newest = {}
    for date, body in zip(blocks[1::2], blocks[2::2]):
        newest[date] = re.findall(r"^\s+- ([a-z0-9_]+)", body, flags=re.M)
    latest = max(newest)
    return latest, newest[latest]


def baseline_lists(tree):
    pkg = Path(tree) / "policyengine_us"
    base_cls = classes(
        pkg / "variables/household/income/spm_unit/spm_unit_benefits.py",
        "spm_unit_benefits",
    )[0]
    spm = string_lists(base_cls)[0][1]
    spm_appends = appended(base_cls)
    _, household = yaml_block_members(
        pkg / "parameters/gov/household/household_benefits.yaml"
    )
    return spm, spm_appends, household


def gaps(tree):
    """{reform: {"spm": (lacks, extra), "household": (lacks, extra)}} under
    default parameters. A copy that reads the parameter, or no copy, has no
    gap. Own benefits are left out of both sides."""
    pkg = Path(tree) / "policyengine_us"
    spm, spm_appends, household = baseline_lists(tree)
    base = {
        "spm": set(spm) | (set(spm_appends) - DEDUCT_PTC_APPENDS),
        "household": set(household),
    }
    result = {}
    for reform, rel in REFORMS.items():
        path = pkg / rel
        result[reform] = {}
        for key, cname in (("spm", "spm_unit_benefits"), ("household", "household_benefits")):
            found = classes(path, cname)
            lists = string_lists(found[0]) if found else []
            if not lists:
                result[reform][key] = ([], [])
                continue
            copy = set(lists[0][1]) | (set(appended(found[0])) - DEDUCT_PTC_APPENDS)
            own = OWN[reform]
            result[reform][key] = (
                sorted(base[key] - copy - own),
                sorted(copy - base[key] - own),
            )
    return result


def main(tree):
    pkg = Path(tree) / "policyengine_us"
    baseline, base_app, household = baseline_lists(tree)
    print(f"baseline SPM list: {len(baseline)} entries")
    print(f"baseline appends: {base_app}")
    print(f"baseline household list: {len(household)} entries")
    for reform, rel in REFORMS.items():
        path = pkg / rel
        print(f"\n== {reform}")
        for cname, base_set, label in (
            ("spm_unit_benefits", set(baseline) | set(base_app), "SPM"),
            ("household_benefits", set(household), "household"),
        ):
            found = classes(path, cname)
            print(f"  {label}: {len(found)} class(es) named {cname}")
            for cls in found[:1]:
                lists = string_lists(cls)
                apps = appended(cls)
                if not lists:
                    src = ast.get_source_segment(path.read_text(), cls) or ""
                    reads = re.findall(r"gov\.household\.[a-z_]+", src)
                    print(
                        f"    no list literal; reads {sorted(set(reads))}; appends {apps}"
                    )
                    continue
                members = lists[0][1]
                copy = set(members) | set(apps)
                lacks = sorted(base_set - copy)
                extra = sorted(copy - base_set)
                print(f"    {lists[0][0]}: {len(members)} entries; appends {apps}")
                ssp = [
                    n
                    for n in lacks
                    if re.search(r"ssp|ssi_state_supplement|state_supplement", n)
                ]
                print(
                    f"    lacks {len(lacks)}: {len(ssp)} named SSI supplements; others "
                    f"{[n for n in lacks if n not in ssp]}"
                )
                print(f"    extra {len(extra)}: {extra}")
    print("\nUnder default parameters, own benefits left out:")
    for reform, parts in gaps(tree).items():
        for key, (lacks, extra) in parts.items():
            print(f"  {reform} {key}: lacks {len(lacks)}, extra {extra}")


if __name__ == "__main__":
    main(sys.argv[1])
