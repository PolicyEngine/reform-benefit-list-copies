"""Who crosses the SPM poverty line when #10662 fixes a reform's benefit list?

Usage:
  python fix_probe.py subset SOURCE_H5 OUT_DIR POLICY YEAR [YEAR ...]
  PYTHONPATH=<tree> python fix_probe.py run OUT_DIR POLICY YEAR SIDE
  python fix_probe.py compare OUT_DIR POLICY YEAR

subset: writes OUT_DIR/subset.h5 with the households of every state whose SPM
benefits change between the national before and after runs of POLICY in any of
the YEARs (runs/<policy>_<side>.json). Households elsewhere get the same
SPM benefits on both sides, and households do not interact in these formulas.

run: runs POLICY (switched on through its in_effect parameter, as reform_lists.py
does) on the subset for YEAR with the tree on PYTHONPATH, and saves per-person
arrays to OUT_DIR/<policy>_<year>_<side>.npz.

compare: checks that each side's subset reproduces the national run's SPM
benefits in every subset state, then reports, by age group, who is in SPM
poverty on each side, who crosses, and, for people in poverty before the fix
whose resources rise, how their gap to the threshold compares with the rise.
"""

import json
import sys
from pathlib import Path

import numpy as np

RUNS = Path(__file__).resolve().parent.parent / "runs"
SWITCHES = {
    "tx_rebate": "gov.contrib.states.tx.rebate.in_effect",
    "end_child_poverty_act": "gov.contrib.congress.tlaib.end_child_poverty_act.in_effect",
    "edaa_end_child_poverty_act": (
        "gov.contrib.congress.tlaib.economic_dignity_for_all_agenda"
        ".end_child_poverty_act.in_effect"
    ),
    "boost_middle_class_tax_credit": "gov.contrib.harris.lift.middle_class_tax_credit.in_effect",
}
FIPS = {
    "AL": 1, "AK": 2, "AZ": 4, "AR": 5, "CA": 6, "CO": 8, "CT": 9, "DE": 10, "DC": 11,
    "FL": 12, "GA": 13, "HI": 15, "ID": 16, "IL": 17, "IN": 18, "IA": 19, "KS": 20,
    "KY": 21, "LA": 22, "ME": 23, "MD": 24, "MA": 25, "MI": 26, "MN": 27, "MS": 28,
    "MO": 29, "MT": 30, "NE": 31, "NV": 32, "NH": 33, "NJ": 34, "NM": 35, "NY": 36,
    "NC": 37, "ND": 38, "OH": 39, "OK": 40, "OR": 41, "PA": 42, "RI": 44, "SC": 45,
    "SD": 46, "TN": 47, "TX": 48, "UT": 49, "VT": 50, "VA": 51, "WA": 53, "WV": 54,
    "WI": 55, "WY": 56,
}


def national(policy, side, year):
    return json.loads((RUNS / f"{policy}_{side}.json").read_text())["years"][str(year)]


def changed_states(policy, years):
    states = set()
    for year in years:
        before = national(policy, "before", year)["by_state"]["spm_unit_benefits"]
        after = national(policy, "after", year)["by_state"]["spm_unit_benefits"]
        states |= {s for s in after if abs(after[s] - before.get(s, 0.0)) > 0.5}
    return sorted(states)


def subset(src, out_dir, policy, years):
    import pandas as pd

    states = changed_states(policy, years)
    print("states:", len(states), " ".join(states), flush=True)
    fips = {FIPS[s] for s in states}
    with pd.HDFStore(src, "r") as store:
        tables = {key.strip("/"): store[key] for key in store.keys()}
    household = tables["household"]
    kept = set(household.loc[household.state_fips.isin(fips), "household_id"])
    person = tables["person"]
    person = person[person.person_household_id.isin(kept)]
    out = {"person": person, "household": household[household.household_id.isin(kept)]}
    for entity in ("tax_unit", "spm_unit", "family", "marital_unit"):
        ids = set(person[f"person_{entity}_id"])
        out[entity] = tables[entity][tables[entity][f"{entity}_id"].isin(ids)]
    out["_time_period"] = tables["_time_period"]
    path = Path(out_dir) / "subset.h5"
    path.unlink(missing_ok=True)
    with pd.HDFStore(path, "w") as store:
        for key, frame in out.items():
            store.put(key, frame)
    (Path(out_dir) / "states.json").write_text(json.dumps(states))
    print({key: len(frame) for key, frame in out.items()}, flush=True)


def run(out_dir, policy, year, side):
    import subprocess

    import policyengine_us
    from policyengine_us import Microsimulation

    tree = Path(policyengine_us.__file__).parent.parent
    commit = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "--short=10", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    reform = {SWITCHES[policy]: {"2024-01-01.2100-12-31": True}}
    sim = Microsimulation(
        reform=reform, dataset=str(Path(out_dir) / "subset.h5"), dataset_end_year=year
    )

    def person(variable):
        return np.asarray(sim.calculate(variable, year, map_to="person").values)

    # As reform_lists.py totals each state: SPM benefits summed to the household,
    # times the household weight.
    household_weight = np.asarray(
        sim.calculate("household_weight", year).values, dtype=float
    )
    states = np.asarray(
        sim.calculate("state_code_str", year, map_to="household").values
    ).astype(str)
    weighted = (
        np.asarray(
            sim.calculate("spm_unit_benefits", year, map_to="household").values,
            dtype=float,
        )
        * household_weight
    )
    by_state = {s: float(weighted[states == s].sum()) for s in sorted(set(states))}
    np.savez(
        Path(out_dir) / f"{policy}_{year}_{side}.npz",
        commit=commit,
        by_state=json.dumps(by_state),
        age=person("age").astype(float),
        weight=np.asarray(sim.calculate("person_weight", year).values, dtype=float),
        poor=person("spm_unit_is_in_spm_poverty").astype(bool),
        deep=person("spm_unit_is_in_deep_spm_poverty").astype(bool),
        resources=person("spm_unit_net_income").astype(float),
        threshold=person("spm_unit_spm_threshold").astype(float),
        benefits=person("spm_unit_benefits").astype(float),
        unit=person("spm_unit_id").astype(int),
        state=person("state_code_str").astype(str),
    )
    print(f"saved {policy} {year} {side} at {commit}", flush=True)


def compare(out_dir, policy, year):
    load = lambda side: np.load(Path(out_dir) / f"{policy}_{year}_{side}.npz")  # noqa: E731
    before, after = load("before"), load("after")
    states = json.loads((Path(out_dir) / "states.json").read_text())
    print(f"{policy} {year}: before at {before['commit']}, after at {after['commit']}")
    for side, arrays in (("before", before), ("after", after)):
        sub = json.loads(str(arrays["by_state"]))
        nat = national(policy, side, year)["by_state"]["spm_unit_benefits"]
        worst = max(abs(sub.get(s, 0.0) - nat[s]) for s in states)
        print(
            f"  {side}: subset reproduces the national run's SPM benefits in all "
            f"{len(states)} states, largest gap ${worst:,.0f}"
        )
        if worst > 1e3:
            sys.exit("refusing: the subset does not reproduce the national run")
    for key in ("age", "weight", "unit", "threshold"):
        if not np.array_equal(before[key], after[key]):
            sys.exit(f"refusing: {key} differs between sides")
    age, w = before["age"], before["weight"]
    gap = before["threshold"] - before["resources"]
    rise = after["resources"] - before["resources"]
    for label, mask in (
        ("children", age < 18),
        ("adults 18-64", (age >= 18) & (age < 65)),
        ("seniors 65+", age >= 65),
    ):
        pb, pa = before["poor"] & mask, after["poor"] & mask
        out_, in_ = pb & ~pa, ~pb & pa
        gained = mask & (rise > 0.5)
        poor_gained = pb & (rise > 0.5)
        print(
            f"  {label}: in poverty before {pb.sum()} records ({w[pb].sum():,.0f}), "
            f"after {pa.sum()} ({w[pa].sum():,.0f}); leave poverty {out_.sum()} "
            f"({w[out_].sum():,.0f}); enter {in_.sum()} ({w[in_].sum():,.0f})"
        )
        print(
            f"    resources rise for {gained.sum()} records ({w[gained].sum():,.0f}), "
            f"{poor_gained.sum()} of them in poverty before ({w[poor_gained].sum():,.0f})"
        )
        if poor_gained.any():
            ratio = rise[poor_gained] / gap[poor_gained]
            closest = np.argmax(ratio)
            print(
                f"    among those in poverty whose resources rise: rise min "
                f"${rise[poor_gained].min():,.0f}, median ${np.median(rise[poor_gained]):,.0f}, "
                f"max ${rise[poor_gained].max():,.0f}; gap min ${gap[poor_gained].min():,.0f}, "
                f"median ${np.median(gap[poor_gained]):,.0f}; largest rise/gap "
                f"{ratio[closest]:.3f} (rise ${rise[poor_gained][closest]:,.0f}, gap "
                f"${gap[poor_gained][closest]:,.0f})"
            )


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "subset":
        subset(sys.argv[2], sys.argv[3], sys.argv[4], [int(y) for y in sys.argv[5:]])
    elif command == "run":
        run(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
    elif command == "compare":
        compare(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    else:
        sys.exit(__doc__)
