"""Twin households for every program a reform copy of the benefit lists left out.

Usage: PYTHONPATH=<tree> python -u household_omissions.py OUT.json YEAR [YEAR ...]

For each program that audit_copies.py found missing from a reform's copy of
household_benefits or spm_unit_benefits at main (and for acp and ebb, which
the Tlaib SPM copies listed although spm_unit_net_income adds both itself),
the script builds two households that differ only in that program: one
receives $1,000 of it as an input, the other none. Each household has one
adult aged 40 with $500,000 of earnings, which rules out every means-tested
response, and one child aged 5, so the End Child Poverty Act pays its child
benefit. The household lives in the program's state (the two-letter prefix of
its name), or in Texas for national programs.

For current law and each of the four reforms, one Simulation holds every
household, and the script records, for each program:

- the change in spm_unit_benefits, household_benefits, spm_unit_net_income and
  household_net_income between the twins (current law adds $1,000 to each
  total that counts the program);
- for each total, the reform's level less current law's for the household
  without the program, next to the reform's own payment, so the reform
  changes each benefit total by its own payment and nothing else.

Every number comes from these simulations; nothing is scaled.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

import policyengine_us
from policyengine_us import Simulation
from policyengine_us.reforms.congress.tlaib.boost.boost_middle_class_tax_credit import (
    boost_middle_class_tax_credit,
)
from policyengine_us.reforms.congress.tlaib.economic_dignity_for_all_agenda.edaa_end_child_poverty_act import (
    end_child_poverty_act as edaa_end_child_poverty_act,
)
from policyengine_us.reforms.congress.tlaib.end_child_poverty_act import (
    end_child_poverty_act,
)
from policyengine_us.reforms.states.tx.rebate.tx_rebate import tx_rebate
from policyengine_us.system import system

AMOUNT = 1_000.0
TOTALS = (
    "spm_unit_benefits",
    "household_benefits",
    "spm_unit_net_income",
    "household_net_income",
)
REFORMS = {
    "baseline": None,
    "tx_rebate": tx_rebate,
    "end_child_poverty_act": end_child_poverty_act,
    "edaa_end_child_poverty_act": edaa_end_child_poverty_act,
    "boost_middle_class_tax_credit": boost_middle_class_tax_credit,
}
# Each reform's own payments, which it adds to the benefit totals on purpose.
OWN = {
    "baseline": [],
    "tx_rebate": ["tx_rebate"],
    "end_child_poverty_act": ["ecpa_child_benefit"],
    "edaa_end_child_poverty_act": ["ecpa_child_benefit"],
    "boost_middle_class_tax_credit": ["boost_middle_class_tax_credit_paid_through_ssa"],
}
# What audit_copies.py found missing at main 097b3c7f8a (and still at #10693's
# head e7ddd42099), by reform and total.
MISSING_SPM_TLAIB = (
    "in_ssp ct_ssp ga_ssp al_ssp ak_ssp dc_ossp id_aabd vt_aabd ky_ssp de_ssp "
    "fl_oss nj_ssp nh_ssp pa_ssp wy_ssp or_ssp nc_sa mt_ssp ok_ssp oh_rss ny_ssp "
    "ri_ssp ut_ssp sd_ssp va_ag ia_ssa ks_sspp hi_oss la_oss md_paa wa_ssp wi_ssp "
    "mi_ssp me_ssp mo_ssp mn_msa ne_aabd nv_oss ca_state_supplement "
    "wa_child_care_subsidies nm_ssi_state_supplement sc_ssi_state_supplement "
    "tx_ssi_state_supplement wv_child_care_subsidies wa_sfa wa_rca"
).split()
MISSING_SPM_TX = (
    "vt_aabd nj_ssp nh_ssp pa_ssp wy_ssp or_ssp nc_sa mt_ssp ok_ssp oh_rss ny_ssp "
    "ri_ssp ut_ssp sd_ssp va_ag ia_ssa wi_ssp nv_oss ca_state_supplement"
).split()
MISSING_HOUSEHOLD = ["commodity_supplemental_food_program", "household_health_benefits"]
COUNTED_TWICE = ["acp", "ebb"]
MISSING = {
    "tx_rebate": {"spm_unit_benefits": MISSING_SPM_TX},
    "end_child_poverty_act": {
        "spm_unit_benefits": MISSING_SPM_TLAIB,
        "household_benefits": MISSING_HOUSEHOLD,
    },
    "edaa_end_child_poverty_act": {"spm_unit_benefits": MISSING_SPM_TLAIB},
    "boost_middle_class_tax_credit": {
        "spm_unit_benefits": MISSING_SPM_TLAIB,
        "household_benefits": MISSING_HOUSEHOLD,
    },
}
PROGRAMS = list(dict.fromkeys(MISSING_SPM_TLAIB + MISSING_HOUSEHOLD + COUNTED_TWICE))
STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
GROUPS = {
    "tax_unit": "tax_units",
    "spm_unit": "spm_units",
    "family": "families",
    "marital_unit": "marital_units",
    "household": "households",
}


def state_of(program):
    prefix = program[:2].upper()
    return prefix if program[2] == "_" and prefix in STATES else "TX"


def situation(year, entities):
    """Two households per program: '<program>-with' and '<program>-without'."""
    people, groups = {}, {plural: {} for plural in GROUPS.values()}
    for program in PROGRAMS:
        for side in ("with", "without"):
            key = f"{program}-{side}"
            adult, child = f"{key}-adult", f"{key}-child"
            people[adult] = {"age": {year: 40}, "employment_income": {year: 500_000}}
            people[child] = {"age": {year: 5}}
            members = {
                "tax_units": [adult, child],
                "spm_units": [adult, child],
                "families": [adult, child],
                "marital_units": [adult],
                "households": [adult, child],
            }
            for plural, who in members.items():
                groups[plural][key] = {"members": who}
            groups["marital_units"][f"{key}-child"] = {"members": [child]}
            groups["households"][key]["state_name"] = {year: state_of(program)}
            value = AMOUNT if side == "with" else 0.0
            entity = entities[program]
            if entity == "person":
                people[adult][program] = {year: value}
            else:
                groups[GROUPS[entity]][key][program] = {year: value}
    return {"people": people, **groups}


def by_household(sim, variable, year):
    values = sim.calculate(variable, year)
    entity = sim.tax_benefit_system.variables[variable].entity.key
    if entity != "household":
        values = sim.calculate(variable, year, map_to="household")
    return np.asarray(values.values if hasattr(values, "values") else values, dtype=float)


def main():
    out, years = Path(sys.argv[1]), [int(y) for y in sys.argv[2:]]
    tree = Path(policyengine_us.__file__).parent.parent
    result = {
        "commit": subprocess.run(
            ["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "tree": str(tree),
        "amount": AMOUNT,
        "years": {},
    }
    for year in years:
        rows = {}
        for name, reform in REFORMS.items():
            entities = {p: system.variables[p].entity.key for p in PROGRAMS}
            sim = Simulation(situation=situation(year, entities), reform=reform)
            variables = sim.tax_benefit_system.variables
            household_ids = list(np.asarray(sim.calculate("household_id", year)))
            # Household order follows the situation's keys.
            keys = [f"{p}-{s}" for p in PROGRAMS for s in ("with", "without")]
            assert len(keys) == len(household_ids)
            levels = {
                total: dict(
                    zip(
                        keys,
                        by_household(sim, total, year).tolist(),
                    )
                )
                for total in TOTALS
            }
            own = {}
            for variable in OWN[name]:
                if variable not in variables:
                    # Main's BOOST copies have no such variable: they append
                    # boost_middle_class_tax_credit only when SSA pays it.
                    ssa = bool(
                        sim.tax_benefit_system.parameters(
                            f"{year}-01-01"
                        ).gov.contrib.congress.tlaib.boost.middle_class_tax_credit.administered_through_ssa
                    )
                    credit = by_household(sim, "boost_middle_class_tax_credit", year)
                    own["boost_middle_class_tax_credit if administered_through_ssa"] = (
                        dict(zip(keys, (credit * ssa).tolist()))
                    )
                    continue
                own[variable] = dict(
                    zip(
                        keys,
                        by_household(sim, variable, year).tolist(),
                    )
                )
            # Each program's own value in the 'with' household, as the
            # simulation reads it back, to confirm the input held.
            read_back = {
                p: float(by_household(sim, p, year)[keys.index(f"{p}-with")])
                for p in PROGRAMS
            }
            rows[name] = {
                "entities": entities,
                "levels": levels,
                "own": own,
                "read_back": read_back,
                "spm_unit_benefits_module": type(variables["spm_unit_benefits"]).__module__,
                "household_benefits_module": type(
                    variables["household_benefits"]
                ).__module__,
            }
            print(f"{year} {name} done", flush=True)
        result["years"][str(year)] = rows
        out.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
