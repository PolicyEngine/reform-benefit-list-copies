"""Why does the Texas rebate leave senior SPM poverty unchanged in the 2027 run?

Usage: PYTHONPATH=<branch tree> python tx_only_probe.py SOURCE_H5 OUT_DIR

Writes the Texas households of the pinned Populace file (every table, rows that
Texas persons reference) to OUT_DIR/tx_only.h5, then runs current law and the
Texas rebate on it for 2027 and reports, for Texas seniors, SPM poverty under
each and the gap between the threshold and SPM resources. Households do not
interact in these formulas, so Texas rows give the same results alone as in the
national file; the script checks that against the national run's Texas totals.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

src, out_dir = sys.argv[1], Path(sys.argv[2])
subset = out_dir / "tx_only.h5"
with pd.HDFStore(src, "r") as store:
    tables = {key.strip("/"): store[key] for key in store.keys()}
household = tables["household"]
tx_households = set(household.loc[household.state_fips == 48, "household_id"])
person = tables["person"]
person = person[person.person_household_id.isin(tx_households)]
out = {"person": person, "household": household[household.household_id.isin(tx_households)]}
for entity in ("tax_unit", "spm_unit", "family", "marital_unit"):
    ids = set(person[f"person_{entity}_id"])
    out[entity] = tables[entity][tables[entity][f"{entity}_id"].isin(ids)]
out["_time_period"] = tables["_time_period"]
subset.unlink(missing_ok=True)
with pd.HDFStore(subset, "w") as store:
    for key, frame in out.items():
        store.put(key, frame)
print({key: len(frame) for key, frame in out.items()}, flush=True)

from policyengine_us import Microsimulation  # noqa: E402

YEAR = 2027
REFORM = {"gov.contrib.states.tx.rebate.in_effect": {"2024-01-01.2100-12-31": True}}
results = {}
for name, reform in (("current law", None), ("Texas rebate", REFORM)):
    sim = Microsimulation(reform=reform, dataset=str(subset), dataset_end_year=YEAR)
    get = lambda v, **k: sim.calculate(v, YEAR, **k).values  # noqa: E731
    row = {
        "age": get("age"),
        "weight": get("person_weight").astype(float),
        "poor": get("spm_unit_is_in_spm_poverty", map_to="person"),
        "resources": get("spm_unit_net_income", map_to="person").astype(float),
        "threshold": get("spm_unit_spm_threshold", map_to="person").astype(float),
        "spm_unit_benefits_total": float(
            (get("spm_unit_benefits").astype(float) * get("spm_unit_weight").astype(float)).sum()
        ),
        "household_benefits_total": float(
            (get("household_benefits").astype(float) * get("household_weight").astype(float)).sum()
        ),
        "people_in_spm_unit": get("spm_unit_size", map_to="person") if "spm_unit_size" in sim.tax_benefit_system.variables else None,
    }
    if reform:
        row["rebate"] = get("tx_rebate", map_to="person").astype(float)
    results[name] = row
    del sim

base, rebate = results["current law"], results["Texas rebate"]
national = json.loads(
    Path(__file__).resolve().parent.parent.joinpath("runs/baseline_after.json").read_text()
)["years"]["2027"]["by_state"]
print(
    "Texas SPM benefits, current law ($bn): subset",
    round(base["spm_unit_benefits_total"] / 1e9, 3),
    "national run",
    round(national["spm_unit_benefits"]["TX"] / 1e9, 3),
)
print(
    "Texas SPM benefits, rebate minus current law ($bn):",
    round((rebate["spm_unit_benefits_total"] - base["spm_unit_benefits_total"]) / 1e9, 3),
)
w = base["weight"]
for label, mask in (
    ("children", base["age"] < 18),
    ("adults 18-64", (base["age"] >= 18) & (base["age"] < 65)),
    ("seniors 65+", base["age"] >= 65),
):
    poor_base, poor_rebate = base["poor"][mask], rebate["poor"][mask]
    gap = (base["threshold"] - base["resources"])[mask]
    added = (rebate["resources"] - base["resources"])[mask]
    print(
        f"{label}: records {mask.sum()}, weighted {w[mask].sum():,.0f}; "
        f"poor under current law {poor_base.sum()} records ({w[mask][poor_base].sum():,.0f}); "
        f"under the rebate {poor_rebate.sum()} ({w[mask][poor_rebate].sum():,.0f}); "
        f"poor records whose gap is below what the rebate adds: {int(((gap > 0) & (gap < added) & poor_base).sum())}"
    )
    if poor_base.any():
        g = gap[poor_base]
        print(f"   poor records' gaps ($): min {g.min():,.0f}, 10th pct {np.percentile(g, 10):,.0f}, median {np.median(g):,.0f}")
        print(f"   what the rebate adds to poor records' resources ($): min {added[poor_base].min():,.0f}, median {np.median(added[poor_base]):,.0f}, max {added[poor_base].max():,.0f}")
