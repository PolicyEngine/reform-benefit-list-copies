"""Check that the add_to_list_parameter property test fails on broken helpers.

Usage: PYTHONPATH=<tree> python mutate_helper.py [--random]

Runs test_add_to_list_parameter_appends_only_missing_names (all its Hypothesis
examples) against the real helper, which must pass, and against each mutant, which
must fail. A mutant the test lets through means the test is too weak.

By default Hypothesis runs derandomized, as CI's profile does; --random draws fresh
examples. Either way the too_slow health check is off: on a cold cache Hypothesis
scans every policyengine_us module for constants during the first draws, which a
loaded host can push past its time limit (2026-11-07 delta review).
"""

import sys

from hypothesis import HealthCheck, settings

# The test's own @settings inherit this profile, so load it before the import.
settings.register_profile(
    "mutate",
    suppress_health_check=[HealthCheck.too_slow],
    derandomize="--random" not in sys.argv,
    database=None,
)
settings.load_profile("mutate")

from policyengine_core.periods import instant as str_to_instant  # noqa: E402

import policyengine_us.tests.test_reform_benefit_lists as module  # noqa: E402


def make(stop_rule="day_before", dedupe=True, skip_none=True, newest_first=True,
         only_missing=True, sort_names=False, in_place=None, bypass_update=False,
         dedupe_members=False, mark="always", clear_cache=False):
    """A helper like the real one, with one bug switched on.

    mark: "always" marks the parameter and its ancestors after every call, as
    the real helper does; "on_change" leaves marking to Parameter.update, so a
    call that adds nothing marks nothing (the helper before 2026-11-07's fix);
    "leaf" sets only the parameter's own flag.
    """
    def helper(parameter, names):
        edit_values(parameter, names)
        if mark == "always":
            parameter.mark_as_modified()
        elif mark == "leaf":
            parameter.modified = True

    def edit_values(parameter, names):
        if sort_names:
            names.sort()  # edits the caller's list
        if dedupe_members:
            for value_at_instant in parameter.values_list:
                if value_at_instant.value is not None:
                    # edits the member list the value shares
                    value_at_instant.value[:] = list(dict.fromkeys(value_at_instant.value))
        if dedupe:
            names = list(dict.fromkeys(names))
        values = list(parameter.values_list)
        if not newest_first:
            values = values[::-1]
        newer_start = None
        for value_at_instant in values:
            members = value_at_instant.value
            if members is not None or not skip_none:
                if only_missing:
                    missing = [n for n in names if n not in members]
                else:
                    missing = list(names)
                if missing:
                    if newer_start is None or stop_rule == "never":
                        stop = None
                    elif stop_rule == "newer_start":
                        stop = str_to_instant(newer_start)
                    else:
                        stop = str_to_instant(newer_start).offset(-1, "day")
                    if in_place == "extend":
                        members.extend(missing)  # edits the list the value shares
                        new_members = members
                    else:
                        new_members = list(members) + missing
                    if bypass_update:
                        # A new list, but set on the value directly: the parent
                        # node's cache and the modified flag never hear of it.
                        value_at_instant.value = new_members
                        if clear_cache:
                            parameter.parent.clear_parent_cache()
                        newer_start = value_at_instant.instant_str
                        continue
                    parameter.update(
                        start=value_at_instant.instant_str,
                        stop=stop,
                        value=new_members,
                    )
                    if in_place == "clear":
                        members.clear()  # empties the list the old value shared
            newer_start = value_at_instant.instant_str

    return helper


MUTANTS = {
    "stop on the newer value's first day (off by one)": make(stop_rule="newer_start"),
    "no stop date (overwrites newer values)": make(stop_rule="never"),
    "names not deduplicated": make(dedupe=False),
    "None values not skipped": make(skip_none=False),
    "oldest value first": make(newest_first=False),
    "names added even when present": make(only_missing=False),
    # From the 2026-11-05 delta review: mutants that edit their inputs in place.
    "sorts the names it is given": make(sort_names=True),
    "extends a member list in place": make(in_place="extend"),
    "clears the member list it read": make(in_place="clear"),
    # From the 2026-11-07 delta review: a helper that skips Parameter.update,
    # and one that dedupes member lists in place.
    "sets values without Parameter.update": make(bypass_update=True),
    "dedupes member lists in place": make(dedupe_members=True),
    # From the 2026-11-07 review of 2080a2eb6c: CountryTaxBenefitSystem clears
    # every flag between its two applications of a reform it is given, and
    # the second call adds nothing; the macro cache reads the flags of folders.
    "marks the parameter only when it adds a name": make(mark="on_change"),
    "marks the parameter but not the nodes above it": make(mark="leaf"),
    "sets values, clears the node cache, flags only the parameter": make(
        bypass_update=True, clear_cache=True, mark="leaf"
    ),
}

test = module.test_add_to_list_parameter_appends_only_missing_names
real = module.add_to_list_parameter
failures = 0

module.add_to_list_parameter = real
try:
    test()
    print("real helper: passes")
except BaseException as error:  # The real helper must pass.
    print(f"real helper: FAILS ({type(error).__name__}: {str(error)[:200]})")
    failures += 1

for name, mutant in MUTANTS.items():
    module.add_to_list_parameter = mutant
    try:
        test()
        print(f"SURVIVED: {name}")
        failures += 1
    except BaseException as error:
        first = str(error).strip().splitlines()[0][:120] if str(error).strip() else ""
        print(f"killed: {name} ({type(error).__name__}: {first})")
module.add_to_list_parameter = real
sys.exit(1 if failures else 0)
