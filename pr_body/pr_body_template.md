Fixes #10226.

## Problem

Four structural reforms that pay a benefit replaced `spm_unit_benefits` with their own copies of its program list, because the list lived in Python where a reform could not extend it. A simulation that turns on one of these reforms uses its copy of `spm_unit_benefits` for every household, so a program the copy lacks drops out of SPM resources in every state. The copies had fallen behind:

| Reform | SPM programs the copy lacked | Counted twice | Household copy lacked |
|---|---|---|---|
| Texas rebate (`tx_rebate`) | 19 state SSI supplements, including `ca_state_supplement` and `wy_ssp` | none | no household copy |
| End Child Poverty Act | 42 SSI supplements, `wa_sfa`, `wa_rca`, `wa_child_care_subsidies`, `wv_child_care_subsidies` | `acp`, `ebb` | `commodity_supplemental_food_program`, `household_health_benefits` |
| EDAA End Child Poverty Act | the same 46 | `acp`, `ebb` | already read the parameter |
| BOOST Act | the same 46 | `acp`, `ebb` | `commodity_supplemental_food_program`, `household_health_benefits` |

The issue asks about the Tlaib copies' other differences. Both trace to baseline changes the copies missed:
- **ACP and EBB.** #8263 (2026-05-12) removed `spm_unit_broadband_subsidy` from the baseline's `spm_unit_benefits` and added `acp` and `ebb` to `spm_unit_net_income`. In the Tlaib copies' SPM lists it swapped `spm_unit_broadband_subsidy` for `acp` and `ebb`, so under those reforms both count twice: once in the copy and again in `spm_unit_net_income`.
- **`aca_ptc`.** #7808 (2026-04-06) changed the baseline formula's `deduct_ptc` append from `aca_ptc` to `assigned_aca_ptc`. The copies kept `aca_ptc`. This matters only under the UBI Center flat tax's `deduct_ptc` switch.

## Change

- **The list.** `spm_unit_benefits` now reads `gov.household.spm_unit_benefits`, a list parameter holding main's 77 programs in main's order.
  - The formula still appends `assigned_aca_ptc` under `deduct_ptc`, then `spm_unit_capped_housing_subsidy` unless `gov.hud.abolition`, in main's order.
  - The housing subsidy stays out of the parameter: `tests/unit/test_spm_measurement_boundary.py` fails any parameter that names an SPM valuation cap.
- **The helper.** `add_to_list_parameter` (in `policyengine_us/tools/parameters.py`) adds names to every dated value of a list parameter.
  - It skips names a value already holds, so applying a reform again changes nothing. `CountryTaxBenefitSystem(reform=R)` applies `R` twice, and `Simulation` and `Microsimulation` apply structural reforms once more.
  - Every call marks the list modified, along with each folder above it, even a call that adds nothing. `CountryTaxBenefitSystem(reform=R)` clears the flags between its two applications of `R`, and core skips its macro cache for a variable when a parameter the variable declares carries the flag. Without this, a reform passed as an object left every list it changes unmarked; the same reform switched on through its `in_effect` parameter kept the flags. The Texas rebate's own `household_state_benefits` edit, which predates this PR, now marks that list the same way. No figure changes: core reads the flag only when a simulation turns its macro cache on, and no reader of these lists declares its parameters.
- **Each reform** adds only its own benefit, to the SPM list and to the household list, and no longer redefines either aggregate:
  - `tx_rebate`, which keeps its 2027-only `household_state_benefits` entry and so reaches `household_benefits` that way;
  - `ecpa_child_benefit`, for both End Child Poverty Act versions;
  - `boost_middle_class_tax_credit_paid_through_ssa`, a new variable: the BOOST credit when SSA pays it, else zero. The old copies counted the credit as a benefit under the same condition.
- **The integrity test.** `test_aggregate_list_integrity.py` drops its checks of the copies. It now fails any reform that redefines a benefit aggregate and points to `add_to_list_parameter`, and it checks that each member of both benefit lists names a variable the model defines and appears only once.

## Invariants

`policyengine_us/tests/test_reform_benefit_lists.py` tests these with Hypothesis, over each of the four reforms and current law:

1. `add_to_list_parameter` keeps every dated value and the members' order, appends only names a value lacks, leaves gaps (`None` values) alone, and changes nothing when run again. It writes new lists and leaves the names it gets and the member lists it reads unchanged. A clone of a parameter shares its member lists, so an edit in place would reach every clone that shares them. It changes values only through `Parameter.update`, so the parent node, which caches what it returns for each day, returns the new lists. Every call marks the parameter and its parent modified, even a call that adds nothing.
   - Hypothesis draws values that start on any day, gaps, and members that repeat, and the test checks each value's first day and the day before it as well as random days, through the parameter and through its parent node. It builds its expectation from copies it takes before the call, and it clears both flags before the second call, as `CountryTaxBenefitSystem` does.
   - A local mutation check ran the test against fourteen broken helpers: stop date off by one day, no stop date, names not deduplicated, gaps not skipped, oldest value first, names added even when present, the given names sorted in place, a member list extended in place, the old member list cleared, values set without `Parameter.update`, member lists deduplicated in place, a flag set only when a name is added, a flag set on the parameter but not its parent, and values set directly with the node's cache cleared and only the parameter flagged. The test fails on all fourteen, with Hypothesis derandomized as in CI and with fresh draws. Earlier versions let eight through: the first drew no gaps and passed the gap mutant; the second built its expectation after the call and passed the sorting and extending mutants; the third read only the parameter, never its node, and drew no repeated members, so it passed the next two; the fourth checked the flag only after a call that changed a value, and only on the parameter, so it passed the last three.
2. Under each reform, each benefit list (`spm_unit_benefits`, `household_benefits`, `household_state_benefits`) in each year from 2015 to 2035 equals the baseline list followed by that reform's own additions, and nothing else. Each reformed system marks modified exactly the lists its reform changes, and current law marks none.
3. Applying a reform once more changes no list.
4. For any one-person household, `spm_unit_benefits` and `household_benefits` equal the sum of the baseline list's programs and the reform's additions, as the simulation computes each. The SPM sum also adds the capped housing subsidy. A program dropped or counted twice breaks the sum.
   - Hypothesis draws the state, a year from 2023 to 2027, and up to eight programs with random amounts, including the reforms' own benefits and ACP and EBB.
5. A dollar of ACP or EBB adds a dollar to `spm_unit_net_income` under current law and under each reform.

Baseline neutrality needs its own evidence, because the properties take the baseline parameter as their oracle:
- the parameter holds main's 77 programs in main's order (an AST comparison against main's Python list), and the formula appends the same two names in the same order;
- the baseline YAML tests that read these aggregates pass unchanged (below);
- current law gives the same totals before and after this change in the microsimulation runs below.

## Tests

- `tests/policy/reform/{tx_rebate,end_child_poverty_act,edaa_end_child_poverty_act,boost}_counts_every_baseline_benefit.yaml`: 24 cases, one reform per file, so each file runs in its own subprocess. __YAML_RESULTS__
- __EXISTING_RESULTS__
- `test_household_spm_resource_parity.py` reads the SPM list from the parameter plus what the formula appends. __PARITY_RESULTS__
- `test_reform_benefit_lists.py` runs in its own Rest group, `reform-benefit-lists`, because it builds a full reformed system for each reform. Locally it peaked at 5.7 GiB RSS; `remaining-heavy` already peaks at 10.5 GiB on main (release run 42082143005), and a shared process would stack the two on a 16 GB runner. __PROP_RESULTS__

## Impact

__IMPACT__

## Conflicts

#9462 (draft), #10086 (draft) and #10569 edit `spm_unit_benefits.py` and all four reform copies. After this lands, each moves its additions into `parameters/gov/household/spm_unit_benefits.yaml` and drops its reform-copy edits.

axiom: n/a: SPM and household benefit aggregate lists; no rule changes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
