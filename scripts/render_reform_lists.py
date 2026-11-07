"""Impact tables and self-checks from reform_lists.py runs (PolicyEngine/policyengine-us#10226).

Usage: python3 render_reform_lists.py RUNS_DIR [--main-tree PATH] [--after-tree PATH]

The trees default to $MAIN_TREE and $AFTER_TREE.

Reads {policy}_{side}.json and {policy}_{side}_{year}.json (the smoke layout) for
side in before (main) and after (the branch), and prints:

- the markdown impact tables, one per year, with a row only where both sides ran;
- the checks below, each PASS or FAIL with its numbers.

Checks, per policy and year:
- modules: before, a reform defines each aggregate it copied; after, no reform
  defines either aggregate;
- list parameter: absent before; after, the branch's baseline list plus only
  the policy's own addition;
- unchanged inputs: market income, people, the own benefit, the state benefits
  list's total, each program's total (where both sides recorded them);
- net income moves with benefits: the change in spm_unit_net_income equals the
  change in spm_unit_benefits, and likewise for the household aggregates
  (both net incomes are adds/subtracts sums of these aggregates);
- decomposition: the change in each aggregate equals the totals of the
  programs the old copy lacked, minus those it counted that the baseline does
  not (copy_gaps.gaps on the main tree, default parameters);
- current law: every recorded number, state totals included, equal on both sides.

Exits 1 if any check fails, so a caller can gate on it.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from copy_gaps import gaps  # noqa: E402

POLICIES = [
    ("baseline", "Current law"),
    ("tx_rebate", "Texas rebate"),
    ("end_child_poverty_act", "End Child Poverty Act"),
    ("edaa_end_child_poverty_act", "EDAA End Child Poverty Act"),
    ("boost_middle_class_tax_credit", "BOOST Act"),
]
# What each policy adds to the branch's SPM list parameter.
OWN_SPM = {
    "baseline": [],
    "tx_rebate": ["tx_rebate"],
    "end_child_poverty_act": ["ecpa_child_benefit"],
    "edaa_end_child_poverty_act": ["ecpa_child_benefit"],
    "boost_middle_class_tax_credit": ["boost_middle_class_tax_credit_paid_through_ssa"],
}
# Aggregates each reform redefined on main (read from the main tree's classes
# by copy_gaps; restated here so a missing class fails the module check).
COPIED = {
    "baseline": set(),
    "tx_rebate": {"spm"},
    "end_child_poverty_act": {"spm", "household"},
    "edaa_end_child_poverty_act": {"spm", "household"},
    "boost_middle_class_tax_credit": {"spm", "household"},
}
REFORM_MODULE = "policyengine_us.reforms."
# Floating point: national sums of ~1e5 records near 1e13 dollars.
REL = 1e-9
ABS = 1.0  # dollars


def close(a, b, scale=None):
    scale = max(abs(a), abs(b), abs(scale or 0.0))
    return abs(a - b) <= max(ABS, REL * scale)


def load(runs):
    data, sources = {}, {}
    for policy, _ in POLICIES:
        for side in ("before", "after"):
            paths = sorted(runs.glob(f"{policy}_{side}.json")) + sorted(
                runs.glob(f"{policy}_{side}_[0-9][0-9][0-9][0-9].json")
            )
            for path in paths:
                run = json.loads(path.read_text())
                if run["policy"] != policy:
                    raise SystemExit(f"{path}: policy {run['policy']}, expected {policy}")
                merged = data.setdefault((policy, side), {k: v for k, v in run.items() if k != "years"} | {"years": {}})
                for key in ("commit", "dataset"):
                    if merged[key] != run[key]:
                        raise SystemExit(f"{path}: {key} {run[key]} differs from {merged[key]}")
                merged["years"].update(run["years"])
                sources.setdefault((policy, side), []).append(path.name)
    return data, sources


def newest_members(path):
    values = yaml.load(path.read_text(), Loader=yaml.BaseLoader)["values"]
    return values[max(values)]


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, ok, label, detail=""):
        self.rows.append((bool(ok), label, detail))

    @property
    def failed(self):
        return [r for r in self.rows if not r[0]]


def bn(x):
    return f"{x / 1e9:,.2f}"


def signed_bn(x):
    return f"{x / 1e9:+,.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path)
    parser.add_argument("--main-tree", type=Path, default=os.environ.get("MAIN_TREE"))
    parser.add_argument("--after-tree", type=Path, default=os.environ.get("AFTER_TREE"))
    args = parser.parse_args()
    if args.main_tree is None or args.after_tree is None:
        raise SystemExit("set MAIN_TREE and AFTER_TREE, or pass --main-tree and --after-tree")

    data, sources = load(args.runs)
    if not data:
        raise SystemExit(f"no runs in {args.runs}")
    gap = gaps(args.main_tree)
    gap["baseline"] = {"spm": ([], []), "household": ([], [])}
    base_spm = newest_members(
        args.after_tree / "policyengine_us/parameters/gov/household/spm_unit_benefits.yaml"
    )
    checks = Checks()

    commits = {side: sorted({d["commit"][:10] for (p, s), d in data.items() if s == side}) for side in ("before", "after")}
    datasets = sorted({d["dataset"] for d in data.values()})
    print(f"Before (main): {commits['before']}; after (branch): {commits['after']}")
    print(f"Dataset: {datasets}")
    checks.add(len(commits["before"]) == 1 and len(commits["after"]) == 1, "one commit per side", str(commits))
    checks.add(len(datasets) == 1, "one dataset", str(datasets))
    print("Files:", {f"{p} {s}": v for (p, s), v in sorted(sources.items())})

    years = sorted({y for d in data.values() for y in d["years"]}, reverse=True)
    for year in years:
        pairs = []
        for policy, label in POLICIES:
            b = data.get((policy, "before"), {}).get("years", {}).get(year)
            a = data.get((policy, "after"), {}).get("years", {}).get(year)
            if a and b:
                pairs.append((policy, label, b, a))
            elif a or b:
                print(f"\n(note: {label} {year} ran on one side only)")
        if not pairs:
            continue

        print(f"\n### {year}\n")
        print("| Policy | SPM benefits before ($bn) | After | Change | SPM poverty before | After | Change (pp) | People in SPM poverty, change | Child SPM poverty, change (pp) | Household benefits, change ($bn) |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for policy, label, b, a in pairs:
            print(
                f"| {label} | {bn(b['spm_unit_benefits'])} | {bn(a['spm_unit_benefits'])} | "
                f"{signed_bn(a['spm_unit_benefits'] - b['spm_unit_benefits'])} | "
                f"{b['spm_percent']:.2f}% | {a['spm_percent']:.2f}% | {a['spm_percent'] - b['spm_percent']:+.3f} | "
                f"{a['people_in_spm_poverty'] - b['people_in_spm_poverty']:+,.0f} | "
                f"{a['child_spm_percent'] - b['child_spm_percent']:+.3f} | "
                f"{signed_bn(a['household_benefits'] - b['household_benefits'])} |"
            )

        print(f"\nDecomposition, {year} ($m): change = programs the copy lacked − programs it counted that the baseline does not\n")
        print("| Policy | Aggregate | Change | Lacked | Counted extra | Expected | Residual |")
        print("|---|---|---|---|---|---|---|")
        for policy, label, b, a in pairs:
            tag = f"{label} {year}"
            # Program totals: the after side's where recorded, else the before side's.
            ta, tb = a.get("program_totals"), b.get("program_totals")
            totals = ta or tb
            if ta and tb:
                worst = max(
                    ((abs(ta[k] - tb[k]), k) for k in ta if k in tb and ta[k] is not None and tb[k] is not None),
                    default=(0.0, None),
                )
                shared = [k for k in ta if k in tb and ta[k] is not None and tb[k] is not None]
                same = all(close(ta[k], tb[k]) for k in shared)
                checks.add(same, f"{tag}: program totals equal on both sides ({len(shared)} programs)", f"largest gap ${worst[0]:,.0f} ({worst[1]})")
            if totals is not None:
                errors = sorted(k for k, v in totals.items() if v is None)
                checks.add(not errors, f"{tag}: every program total computed ({len(totals)})", str(errors))

            # Modules.
            for key, field in (("spm", "spm_unit_benefits_module"), ("household", "household_benefits_module")):
                before_reform = b[field].startswith(REFORM_MODULE)
                after_reform = a[field].startswith(REFORM_MODULE)
                checks.add(
                    before_reform == (key in COPIED[policy]) and not after_reform,
                    f"{tag}: {field} from {'a reform' if key in COPIED[policy] else 'the baseline'} before, the baseline after",
                    f"before {b[field]}; after {a[field]}",
                )

            # List parameter.
            checks.add(b.get("spm_unit_benefits_parameter") is None, f"{tag}: main has no SPM list parameter")
            checks.add(
                a.get("spm_unit_benefits_parameter") == base_spm + OWN_SPM[policy],
                f"{tag}: branch SPM list = baseline {len(base_spm)} + {OWN_SPM[policy]}",
                f"got {len(a.get('spm_unit_benefits_parameter') or [])} entries",
            )

            # Inputs the change must leave alone.
            for field in ("people", "spm_unit_market_income", "household_market_income", "household_state_benefits", "acp", "ebb", "own_benefit_total"):
                if field in a or field in b:
                    checks.add(close(a.get(field, math.nan), b.get(field, math.nan)), f"{tag}: {field} unchanged", f"{b.get(field)} -> {a.get(field)}")

            # Net incomes move one for one with benefits.
            for net, benefits in (("spm_unit_net_income", "spm_unit_benefits"), ("household_net_income", "household_benefits")):
                d_net, d_ben = a[net] - b[net], a[benefits] - b[benefits]
                checks.add(close(d_net, d_ben, a[net]), f"{tag}: change in {net} = change in {benefits}", f"{d_net:,.0f} vs {d_ben:,.0f}")

            # Decomposition.
            for key, field in (("spm", "spm_unit_benefits"), ("household", "household_benefits")):
                lacks, extra = gap[policy][key]
                change = a[field] - b[field]
                if totals is None:
                    checks.add(False, f"{tag}: {field} decomposition", "no program totals on either side")
                    continue
                missing = [n for n in lacks + extra if totals.get(n) is None]
                lacked = sum(totals.get(n) or 0.0 for n in lacks)
                counted = sum(totals.get(n) or 0.0 for n in extra)
                expected = lacked - counted
                residual = change - expected
                ok = not missing and close(change, expected, a[field])
                checks.add(ok, f"{tag}: {field} change = lacked − counted extra", f"residual ${residual:,.0f}; missing totals {missing}")
                print(
                    f"| {label} | `{field}` | {change / 1e6:+,.1f} | {lacked / 1e6:,.1f} ({len(lacks)}) | "
                    f"{counted / 1e6:,.1f} ({', '.join(extra) or 'none'}) | {expected / 1e6:+,.1f} | {residual:+,.0f} dollars |"
                )

            if policy == "baseline":
                numbers = [k for k, v in a.items() if isinstance(v, float)]
                diff = [k for k in numbers if not close(a[k], b.get(k, math.nan))]
                checks.add(not diff, f"{tag}: every number equal on both sides ({len(numbers)})", str(diff))
                states = [
                    (name, s)
                    for name, by in a["by_state"].items()
                    for s, v in by.items()
                    if not close(v, b["by_state"][name].get(s, math.nan))
                ]
                checks.add(not states, f"{tag}: every state total equal on both sides", str(states[:5]))
                checks.add(a["spm_unit_benefits_parameter"] == base_spm, f"{tag}: branch list is the {len(base_spm)}-program baseline")

        print(f"\nLargest state changes in SPM benefits, {year} ($m):\n")
        for policy, label, b, a in pairs:
            if policy == "baseline":
                continue
            sb, sa = b["by_state"]["spm_unit_benefits"], a["by_state"]["spm_unit_benefits"]
            change = sorted(((sa[s] - sb[s], s) for s in sa), key=lambda t: -abs(t[0]))
            moved = [t for t in change if abs(t[0]) > ABS]
            print(f"- {label}: {len(moved)} states change; " + ", ".join(f"{s} {d / 1e6:+,.1f}" for d, s in change[:8]))
            nat = a["spm_unit_benefits"] - b["spm_unit_benefits"]
            total = sum(d for d, _ in change)
            # by_state maps the SPM aggregate to households, so its sum matches the
            # national change only when every SPM unit's weight equals its household's.
            print(f"  state changes sum to {total / 1e6:+,.1f}; national {nat / 1e6:+,.1f}")

        print(f"\nOwn benefit and poverty detail, {year}:\n")
        print(
            "| Policy | Own benefit ($bn), before → after | SPM poverty | Child | Senior | Deep SPM poverty "
            "| People in SPM poverty, change | People in deep SPM poverty, change |"
        )
        print("|---|---|---|---|---|---|---|---|")
        for policy, label, b, a in pairs:
            own = (
                f"`{a['own_benefit']}` {bn(b['own_benefit_total'])} → {bn(a['own_benefit_total'])}"
                if "own_benefit" in a
                else "none"
            )
            rates = " | ".join(
                f"{b[key]:.4f}% → {a[key]:.4f}%"
                for key in ("spm_percent", "child_spm_percent", "senior_spm_percent", "deep_spm_percent")
            )
            print(
                f"| {label} | {own} | {rates} "
                f"| {a['people_in_spm_poverty'] - b['people_in_spm_poverty']:+,.0f} "
                f"| {a['people_in_deep_spm_poverty'] - b['people_in_deep_spm_poverty']:+,.0f} |"
            )

    print("\n## Checks\n")
    for ok, label, detail in checks.rows:
        print(f"- {'PASS' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    print(f"\n{len(checks.rows) - len(checks.failed)} of {len(checks.rows)} checks pass")
    sys.exit(1 if checks.failed else 0)


if __name__ == "__main__":
    main()
