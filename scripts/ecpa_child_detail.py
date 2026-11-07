"""Why the #10662 fix leaves child SPM poverty unchanged under the End Child Poverty
Act in 2027 but lowers it in 2024.

Usage: python ecpa_child_detail.py PROBE_DIR EDAA_PROBE_DIR

Reads fix_probe.py's end_child_poverty_act npz files for 2024 and 2027 (the 19
states where the fix changes SPM benefits; both years come from the same subset
file, so person i is the same record in each) and the
edaa_end_child_poverty_act files for 2027, and writes PROBE_DIR/child_detail.json:

- 2027: the child records that leave poverty with the fix, and their total weight,
  under each version, and whether both versions lift the same records;
- the share of child records whose weight is under one person, and the weight they hold;
- 2024: the heaviest child record that leaves poverty, its family's gap to the
  threshold and what the fix adds, and the same record in 2027.
"""

import json
import sys
from pathlib import Path

import numpy as np

probe, edaa_probe = Path(sys.argv[1]), Path(sys.argv[2])


def load(year, side, policy="end_child_poverty_act", folder=probe):
    return np.load(folder / f"{policy}_{year}_{side}.npz")


b24, a24, b27, a27 = load(2024, "before"), load(2024, "after"), load(2027, "before"), load(2027, "after")
for key in ("unit", "age"):
    if not np.array_equal(b24[key], b27[key]):
        sys.exit(f"refusing: {key} differs between the 2024 and 2027 files")
eb27, ea27 = (load(2027, side, "edaa_end_child_poverty_act", edaa_probe) for side in ("before", "after"))
for key in ("unit", "age", "weight", "state"):
    if not np.array_equal(b27[key], eb27[key]):
        sys.exit(f"refusing: {key} differs between the two versions' 2027 files")


def crossing(before, after):
    return np.flatnonzero(before["poor"] & ~after["poor"] & (before["age"] < 18))


out = {}
cross27 = crossing(b27, a27)
out["crossing_2027"] = {
    "records": int(len(cross27)),
    "weight": float(b27["weight"][cross27].sum()),
    "max_weight": float(b27["weight"][cross27].max()) if len(cross27) else 0.0,
}
edaa_cross27 = crossing(eb27, ea27)
out["crossing_2027_edaa"] = {
    "records": int(len(edaa_cross27)),
    "weight": float(eb27["weight"][edaa_cross27].sum()),
    "same_records": bool(np.array_equal(cross27, edaa_cross27)),
}
child = b27["age"] < 18
light = child & (b27["weight"] < 1)
out["light_children_2027"] = {
    "records": int(child.sum()),
    "under_one": int(light.sum()),
    "under_one_weight": float(b27["weight"][light].sum()),
    "children": float(b27["weight"][child].sum()),
}
cross24 = crossing(b24, a24)
heaviest = int(cross24[np.argmax(b24["weight"][cross24])])
out["crossing_2024"] = {
    "records": int(len(cross24)),
    "weight": float(b24["weight"][cross24].sum()),
}


def record(before, after, i):
    return {
        "state": str(before["state"][i]),
        "age": float(before["age"][i]),
        "weight": float(before["weight"][i]),
        "poor_before": bool(before["poor"][i]),
        "poor_after": bool(after["poor"][i]),
        "resources_before": float(before["resources"][i]),
        "threshold": float(before["threshold"][i]),
        "gap": float(before["threshold"][i] - before["resources"][i]),
        "rise": float(after["resources"][i] - before["resources"][i]),
    }


out["heaviest_2024"] = {"2024": record(b24, a24, heaviest), "2027": record(b27, a27, heaviest)}
(probe / "child_detail.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
