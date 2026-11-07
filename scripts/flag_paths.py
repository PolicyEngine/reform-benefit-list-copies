"""Which build paths leave the benefit lists marked modified?

Usage: PYTHONPATH=<tree> python flag_paths.py [case substring ...]
Prints each list's modified flag for the baseline, for each reform passed as an
object, and for each reform switched on through its in_effect parameter.
"""
import gc
import sys

from policyengine_core.reforms import Reform

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
from policyengine_us.system import CountryTaxBenefitSystem, system

LISTS = ("spm_unit_benefits", "household_benefits", "household_state_benefits")


def flags(tbs):
    node = tbs.parameters.gov.household
    return " ".join(f"{n}={getattr(node, n).modified}" for n in LISTS) + (
        f" | gov.household={node.modified}"
    )


print("baseline:", flags(system), flush=True)
SWITCHES = {
    "tx_rebate": "gov.contrib.states.tx.rebate.in_effect",
    "end_child_poverty_act": "gov.contrib.congress.tlaib.end_child_poverty_act.in_effect",
    "edaa_end_child_poverty_act": (
        "gov.contrib.congress.tlaib.economic_dignity_for_all_agenda"
        ".end_child_poverty_act.in_effect"
    ),
    "boost": "gov.contrib.harris.lift.middle_class_tax_credit.in_effect",
}
OBJECTS = {
    "tx_rebate": tx_rebate,
    "end_child_poverty_act": end_child_poverty_act,
    "edaa_end_child_poverty_act": edaa_end_child_poverty_act,
    "boost": boost_middle_class_tax_credit,
}
cases = {}
for name in OBJECTS:
    cases[f"{name} object"] = OBJECTS[name]
    cases[f"{name} via in_effect"] = Reform.from_dict(
        {SWITCHES[name]: {"2024-01-01.2100-12-31": True}}, country_id="us"
    )
only = sys.argv[1:]
for name, reform in cases.items():
    if only and not any(o in name for o in only):
        continue
    tbs = CountryTaxBenefitSystem(reform=reform)
    print(f"{name}:", flags(tbs), flush=True)
    del tbs
    gc.collect()
