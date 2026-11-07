"""One policyengine-us tree and one policy on the whole pinned Populace file.

Usage: PYTHONPATH=<tree> python reform_lists.py OUT.json POLICY YEAR [YEAR ...]

POLICY is baseline or one of the four structural reforms that pay a benefit
(PolicyEngine/policyengine-us#10226). The reform's in_effect switch turns on
from 2024, so create_structural_reforms_from_parameters applies the reform.
Each year gets a fresh Microsimulation.
"""

import gc
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import yaml


STARTED = time.time()


def mark(step):
    """Log elapsed seconds and this process's memory footprint (macOS `footprint`)."""
    try:
        text = subprocess.run(
            ["footprint", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
        found = re.search(r"phys_footprint:\s+([\d.]+)\s+(\w+)", text)
        memory = f"{found.group(1)} {found.group(2)}" if found else "unread"
    except Exception as error:  # A log line must never stop a run.
        memory = f"unread ({type(error).__name__})"
    print(f"[mem] {time.time() - STARTED:7.0f}s {memory:>12}  {step}", flush=True)


mark("start")
import policyengine_us
from policyengine_us import Microsimulation
from policyengine_us.system import DEFAULT_DATASET

mark("imported")

SWITCHES = {
    "baseline": None,
    "tx_rebate": "gov.contrib.states.tx.rebate.in_effect",
    "end_child_poverty_act": "gov.contrib.congress.tlaib.end_child_poverty_act.in_effect",
    "edaa_end_child_poverty_act": (
        "gov.contrib.congress.tlaib.economic_dignity_for_all_agenda"
        ".end_child_poverty_act.in_effect"
    ),
    "boost_middle_class_tax_credit": (
        "gov.contrib.harris.lift.middle_class_tax_credit.in_effect"
    ),
}
# The benefit each reform pays.
OWN = {
    "tx_rebate": "tx_rebate",
    "end_child_poverty_act": "ecpa_child_benefit",
    "edaa_end_child_poverty_act": "ecpa_child_benefit",
    "boost_middle_class_tax_credit": "boost_middle_class_tax_credit",
}
# Every program that can explain a change in the two aggregates: the branch's
# baseline lists, what the formula appends, the programs the reform copies
# listed (acp, ebb, aca_ptc), and the reforms' own benefits. Both trees read
# these names from the branch's parameter files (the tree at AFTER_TREE), so they
# total the same set.
LISTS = Path(os.environ["AFTER_TREE"]) / "policyengine_us/parameters/gov/household"


def newest_members(name):
    """Members of a list parameter's newest dated value. BaseLoader keeps the
    date keys as strings, since PyYAML cannot read year 0000 as a date."""
    values = yaml.load((LISTS / name).read_text(), Loader=yaml.BaseLoader)["values"]
    return values[max(values)]


PROGRAMS = list(
    dict.fromkeys(
        newest_members("spm_unit_benefits.yaml")
        + newest_members("household_benefits.yaml")
        + [
            "spm_unit_capped_housing_subsidy",
            "assigned_aca_ptc",
            "aca_ptc",
            "acp",
            "ebb",
            "commodity_supplemental_food_program",
            "household_health_benefits",
            "tx_rebate",
            "ecpa_child_benefit",
            "boost_middle_class_tax_credit",
            "boost_middle_class_tax_credit_paid_through_ssa",
        ]
    )
)

out, policy, years = sys.argv[1], sys.argv[2], [int(y) for y in sys.argv[3:]]
done = {}
if Path(out).exists():
    # A crash keeps the years already saved; rerunning computes the rest.
    done = json.loads(Path(out).read_text())["years"]
switch = SWITCHES[policy]
reform = {switch: {"2024-01-01.2100-12-31": True}} if switch else None
tree = Path(policyengine_us.__file__).parent.parent
result = {
    "commit": subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip(),
    "tree": str(tree),
    "dataset": DEFAULT_DATASET,
    "policy": policy,
    "years": done,
}

for year in years:
    if str(year) in done:
        continue
    # REFORM_LISTS_DATASET points a smoke test at a sample file. Published figures
    # come only from runs without it, on DEFAULT_DATASET.
    sample = os.environ.get("REFORM_LISTS_DATASET")
    if sample:
        result["dataset"] = sample
    sample_kwargs = {"dataset": sample, "dataset_end_year": year} if sample else {}
    sim = Microsimulation(reform=reform, **sample_kwargs)
    mark("Microsimulation built")
    system = sim.tax_benefit_system
    spm_class = type(system.variables["spm_unit_benefits"])
    household_class = type(system.variables["household_benefits"])
    person_weight = sim.calculate("person_weight", year).values.astype(float)
    spm_weight = sim.calculate("spm_unit_weight", year).values.astype(float)
    household_weight = sim.calculate("household_weight", year).values.astype(float)
    age = sim.calculate("age", year).values
    mark("weights and age")
    poor = sim.calculate("spm_unit_is_in_spm_poverty", year, map_to="person").values
    mark("spm_unit_is_in_spm_poverty")
    deep = sim.calculate(
        "spm_unit_is_in_deep_spm_poverty", year, map_to="person"
    ).values
    mark("spm_unit_is_in_deep_spm_poverty")
    children = age < 18
    seniors = age >= 65
    row = {
        # Where the aggregates come from: a reform module on main, the
        # baseline variable on the branch.
        "spm_unit_benefits_module": spm_class.__module__,
        "household_benefits_module": household_class.__module__,
        "people": float(person_weight.sum()),
        "spm_percent": float(100 * np.average(poor, weights=person_weight)),
        "child_spm_percent": float(
            100 * np.average(poor[children], weights=person_weight[children])
        ),
        "senior_spm_percent": float(
            100 * np.average(poor[seniors], weights=person_weight[seniors])
        ),
        "deep_spm_percent": float(100 * np.average(deep, weights=person_weight)),
        "people_in_spm_poverty": float((poor * person_weight).sum()),
        "people_in_deep_spm_poverty": float((deep * person_weight).sum()),
    }
    try:
        # Only the branch has this parameter. Reading the one parameter builds
        # no parameter tree beyond the ones the formulas already built.
        row["spm_unit_benefits_parameter"] = list(
            system.parameters.gov.household.spm_unit_benefits(f"{year}-01-01")
        )
    except Exception:
        row["spm_unit_benefits_parameter"] = None
    for name in (
        "spm_unit_market_income",
        "spm_unit_benefits",
        "spm_unit_net_income",
        "acp",
        "ebb",
    ):
        row[name] = float((sim.calculate(name, year).values.astype(float) * spm_weight).sum())
        mark(name)
    for name in (
        "household_market_income",
        "household_benefits",
        "household_state_benefits",
        "household_net_income",
    ):
        row[name] = float(
            (sim.calculate(name, year).values.astype(float) * household_weight).sum()
        )
        mark(name)
    if policy in OWN:
        own = sim.calculate(OWN[policy], year, map_to="household").values.astype(float)
        row["own_benefit"] = OWN[policy]
        row["own_benefit_total"] = float((own * household_weight).sum())
        mark(OWN[policy])
    # Each program's weighted national total, at its own entity, for the
    # renderer's check that a change in an aggregate equals the totals of the
    # programs the change adds or removes.
    totals, entities = {}, {}
    for name in PROGRAMS:
        if name not in system.variables:
            continue
        try:
            entity = system.variables[name].entity.key
            values = sim.calculate(name, year).values.astype(float)
            weights = sim.calculate(f"{entity}_weight", year).values.astype(float)
            totals[name] = float((values * weights).sum())
            entities[name] = entity
        except Exception as error:  # A total must never stop a run.
            totals[name] = None
            entities[name] = f"error: {type(error).__name__}: {error}"[:200]
    row["program_totals"] = totals
    row["program_entities"] = entities
    mark("program totals")
    states = sim.calculate("state_code_str", year, map_to="household").values.astype(str)
    by_state = {}
    for name in ("spm_unit_benefits", "spm_unit_net_income", "household_benefits"):
        values = sim.calculate(name, year, map_to="household").values.astype(float)
        weighted = values * household_weight
        by_state[name] = {s: float(weighted[states == s].sum()) for s in sorted(set(states))}
    mark("by state")
    row["by_state"] = by_state
    result["years"][str(year)] = row
    print(
        policy,
        year,
        {
            k: v
            for k, v in row.items()
            if k
            not in (
                "by_state",
                "spm_unit_benefits_parameter",
                "program_totals",
                "program_entities",
            )
        },
        flush=True,
    )
    temporary = Path(out + ".tmp")
    temporary.write_text(json.dumps(result, indent=1) + "\n")
    temporary.replace(out)
    del sim
    gc.collect()
